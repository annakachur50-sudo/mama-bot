"""Paid AI skincare flow for Mama 24/7.

The module reuses the bot's configured Gemini client and the existing YooKassa
payment integration. Photos are downloaded to memory only and never persisted.
"""
from __future__ import annotations

import asyncio
import html
import io
import logging
import re
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from google.genai import types

from payments import (
    PaymentConfigurationError,
    create_care_pending_order_sync,
    create_yookassa_payment,
    get_care_access_order_sync,
    get_care_order_sync,
    has_care_access_sync,
    mark_care_result_status_sync,
    record_care_photo_consent_sync,
    has_care_photo_consent_sync,
    save_care_payment_id_sync,
    save_care_result_sync,
    set_care_order_mode_sync,
    update_care_order_answers_sync,
)

logger = logging.getLogger("telegram-gemini-bot.care")
care_router = Router(name="care")

_bot = None
_client = None
_model = "gemini-3.5-flash-lite"


class CareStates(StatesGroup):
    waiting_for_mode = State()
    waiting_for_payment = State()
    waiting_for_consent = State()
    waiting_for_photo_category = State()
    waiting_for_photo = State()
    survey_skin_type = State()
    survey_concern = State()
    survey_brand_pref = State()
    generating_result = State()


def configure_care_handlers(bot: Any, gemini_client: Any, model: str) -> None:
    global _bot, _client, _model
    _bot, _client, _model = bot, gemini_client, model
    logger.info("Care Gemini client configured: model=%s", _model)


def care_mode_keyboard(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Анализ кожи по селфи", callback_data=f"care:mode:photo:{order_id}")],
        [InlineKeyboardButton(text="📝 Ответить на 3 вопроса", callback_data=f"care:mode:quiz:{order_id}")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")],
    ])


def care_payment_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате 99 ₽", url=url)],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")],
    ])


def care_consent_keyboard(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Согласна, продолжить", callback_data=f"care:consent:yes:{order_id}")],
        [InlineKeyboardButton(text="↩️ Назад к выбору", callback_data=f"care:back:mode:{order_id}")],
    ])


def care_photo_category_keyboard(order_id: str) -> InlineKeyboardMarkup:
    options = [
        ("🌿 Натуральные эко-линейки и травы", "natural"),
        ("✨ Корейский уход и современные активы", "korean"),
        ("🧴 Аптека и базовый комфорт", "pharmacy"),
        ("💛 Не принципиально / Микс", "mix"),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"care:photo_category:{key}:{order_id}")]
        for label, key in options
    ] + [[InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")]])


async def _ask_care_photo_category(message: Message, state: FSMContext, order_id: str) -> None:
    await state.set_state(CareStates.waiting_for_photo_category)
    await message.answer(
        "Шаг: Какому уходу отдаёшь предпочтение? 🌸",
        reply_markup=care_photo_category_keyboard(order_id),
    )


def care_quiz_keyboard(question: str, order_id: str) -> InlineKeyboardMarkup:
    options = {
        "skin": [
            ("Сухая / тонкая", "dry"), ("Нормальная / комбинированная", "combo"),
            ("Жирная / пористая", "oily"), ("Не знаю точно", "unknown"),
        ],
        "concern": [
            ("Сухость и шелушения", "dryness"), ("Поры, чёрные точки, блеск", "pores"),
            ("Тусклый цвет, следы усталости", "dull"), ("Тонус, мелкие морщинки", "tone"),
            ("Чувствительность и дискомфорт", "sensitive"),
        ],
        "brand": [
            ("🌿 Натуральные эко-линейки", "green"), ("✨ Корейский уход и современные активы", "korean"),
            ("🧴 Аптека и базовый комфорт", "pharmacy"), ("💛 Не принципиально", "any"),
        ],
    }
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"care:quiz:{question}:{key}:{order_id}")]
        for label, key in options[question]
    ] + [[InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")]])


def care_result_keyboard(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Повторить подбор", callback_data=f"care:repeat:{order_id}")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")],
    ])

async def _delete_callback_message(callback: CallbackQuery) -> None:
    """Remove a consumed inline-keyboard message without interrupting the flow."""
    if callback.message is None:
        return
    try:
        await callback.message.delete()
    except Exception as error:
        # Telegram may reject deletion (for example, for an old/inaccessible message).
        # The next step should still be delivered so the user is never stuck.
        logger.debug("Could not delete care step message: %s", error)



def _format_result(value: str) -> str:
    safe = html.escape(value.strip(), quote=False)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe, flags=re.DOTALL)
    return safe.replace("**", "")


def _split_text(value: str, limit: int = 3600) -> list[str]:
    chunks: list[str] = []
    remaining = value
    while len(remaining) > limit:
        cut = remaining.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def start_care_checkout(callback: CallbackQuery, state: FSMContext | None = None) -> None:
    """Entry point called by the existing radiance menu handler."""
    if callback.message is None:
        await callback.answer()
        return
    await callback.answer()
    user_id = callback.from_user.id
    try:
        if await asyncio.to_thread(has_care_access_sync, user_id):
            order_id = await asyncio.to_thread(get_care_access_order_sync, user_id)
            if not order_id:
                raise RuntimeError("Care access exists without an order")
            if state is not None:
                await state.clear()
                await state.set_state(CareStates.waiting_for_mode)
                await state.update_data(order_id=order_id)
            await callback.message.answer(
                "Доступ к персональному уходу уже открыт 🌸\n\nКак тебе удобнее подобрать уход?",
                reply_markup=care_mode_keyboard(order_id),
            )
            return
        order_id = await asyncio.to_thread(create_care_pending_order_sync, user_id)
        if state is not None:
            await state.clear()
            await state.set_state(CareStates.waiting_for_payment)
            await state.update_data(order_id=order_id)
        payment = await create_yookassa_payment(order_id, user_id, service_type="care")
        await asyncio.to_thread(save_care_payment_id_sync, order_id, payment["id"])
        await callback.message.answer(
            "🌸 <b>Персональный подбор ухода и косметики</b>\n\n"
            "Стоимость услуги — <b>99 ₽</b>. После подтверждения оплаты выберешь удобный формат: "
            "анализ по селфи или короткую анкету.\n\n"
            "Нажми кнопку, чтобы перейти на защищённую страницу ЮKassa 💳",
            reply_markup=care_payment_keyboard(payment["confirmation_url"]),
            parse_mode="HTML",
        )
    except PaymentConfigurationError:
        logger.error("Care payment configuration is incomplete")
        await callback.message.answer("Оплата пока недоступна. Попробуй немного позже 🌿")
    except Exception as error:
        logger.warning("Could not start care checkout (%s)", type(error).__name__)
        await callback.message.answer(
            "Не получилось подготовить оплату. Если страница ЮKassa уже открывалась, "
            "не оплачивай повторно — сначала дождись подтверждения 🌿"
        )


async def send_care_result(message: Message, order_id: str, user_id: int, prompt: str,
                           image_bytes: bytes | None = None) -> None:
    if _client is None:
        await message.answer("Анализ временно недоступен. Попробуй ещё раз чуть позже 🌿")
        return
    await asyncio.to_thread(mark_care_result_status_sync, order_id, user_id, "processing")
    status = await message.answer("🌸 Подбираю уход и собираю рекомендации…")
    try:
        parts = [types.Part.from_text(text=prompt)]
        if image_bytes is not None:
            # Telegram photo messages are delivered as JPEG; keep the original bytes in memory.
            logger.info(
                "Care vision request: model=%s mime_type=image/jpeg image_bytes=%d",
                _model,
                len(image_bytes),
            )
            parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
        response = await asyncio.wait_for(
            asyncio.to_thread(
                _client.models.generate_content,
                model=_model,
                contents=[types.Content(role="user", parts=parts)],
            ),
            # The shared SDK client has a 120s HTTP timeout; keep this outer
            # guard slightly longer so the SDK can return its actual API error.
            timeout=125,
        )
        result = (response.text or "").strip()
        if not result:
            raise RuntimeError("Gemini returned an empty care result")
        await asyncio.to_thread(save_care_result_sync, order_id, user_id, result)
        formatted = _format_result(result)
        chunks = _split_text(formatted)
        for index, chunk in enumerate(chunks):
            await message.answer(
                chunk,
                reply_markup=care_result_keyboard(order_id) if index == len(chunks) - 1 else None,
                parse_mode="HTML",
            )
        try:
            await status.delete()
        except Exception:
            pass
    except asyncio.CancelledError:
        raise
    except Exception as error:
        if image_bytes is not None:
            logger.exception("Care vision error: %s", error)
        else:
            logger.exception("Care generation error: %s", error)
        try:
            await asyncio.to_thread(mark_care_result_status_sync, order_id, user_id, "failed")
        except Exception:
            logger.warning("Could not persist care generation failure")
        try:
            await status.edit_text(
                "Оплата сохранена, но сейчас не получилось подготовить рекомендации 🙈 "
                "Попробуй повторить позже — второй раз платить не нужно.",
                reply_markup=care_result_keyboard(order_id),
            )
        except Exception:
            await message.answer(
                "Оплата сохранена, но сейчас не получилось подготовить рекомендации 🙈 "
                "Попробуй повторить позже — второй раз платить не нужно.",
                reply_markup=care_result_keyboard(order_id),
            )


def _photo_prompt(cosmetics_category: str) -> str:
    return (
        "Ты — бережный ИИ-помощник по уходу за кожей. Анализируй только видимые особенности кожи на фото. "
        "Не ставь диагнозы и не утверждай наличие акне, розацеа, дерматита или иных заболеваний. "
        "Не делай категоричных выводов по одному фото; освещение, камера, фильтры и макияж могут искажать картину. "
        "Если качество недостаточное, честно скажи об этом и не придумывай признаки. Не обещай лечение или гарантированный результат. "
        "Не назначай препараты. Не рекомендуй агрессивные сочетания активов. "
        "Составь структурированный ответ на русском, на «ты», дружелюбно и без медицинского жаргона. "
        "Используй заголовок «🌸 ТВОЙ ПЕРСОНАЛЬНЫЙ УХОД», затем разделы: "
        "💧 Что учитываем; ☀️ Утренний ритуал (очищение, основной уход, увлажнение, SPF); "
        "🌙 Вечерний ритуал (очищение, основной актив или сыворотка, восстановление и увлажнение); "
        "✨ Подходящие компоненты (2–3); 🧴 На что обратить внимание при выборе косметики; 🤍 Маленький совет. "
        "Предпочтительная категория косметики пользователя: " + cosmetics_category + ". "
        "Подбирай рекомендации предметно внутри выбранного сегмента и приводи 2–3 конкретных примера типов линеек/средств: "
        "для натурального сегмента — растительные и сибирские эко-серии; для корейского — пептидные и современные активные линейки; "
        "для аптечного — барьерные кремы и базовые дерматокосметические серии. Не выдумывай названия брендов, конкретных линеек, "
        "составы или наличие товаров: если не уверен в существовании конкретного продукта, опиши тип линейки без названия. "
        "Запрещено использовать списки со звёздочками (* пункт). Вместо маркерных точек используй тематические эмодзи "
        "в начале строк: 💧, 🌿, ☀️, 🌙, ✨, 🧴. Текст должен быть эстетичным, с абзацами и выделением ключевых активов "
        "жирным шрифтом, без markdown-маркеров списков. "
        "Укажи вводить новые средства постепенно и сделать патч-тест."
    )


def _quiz_prompt(answers: dict[str, str]) -> str:
    labels = {
        "skin_type": "Тип кожи",
        "concern": "Что хочется улучшить",
        "brand_pref": "Предпочтения по уходу",
    }
    details = "\n".join(f"{labels.get(key, key)}: {value}" for key, value in answers.items())
    return (
        "Ты — бережный ИИ-помощник по уходу за кожей. Составь персональный базовый план только на основании ответов. "
        "Не ставь медицинские диагнозы, не назначай препараты и не обещай лечение заболеваний. "
        "Не выдумывай аллергию, заболевания, продукты и составы. Если есть чувствительность, предложи мягкий минималистичный уход. "
        "Сформируй ответ на русском, на «ты», дружелюбно и без медицинского жаргона. "
        "Заголовок «🌸 ТВОЙ ПЕРСОНАЛЬНЫЙ УХОД», разделы: 💧 Что учитываем; ☀️ Утренний ритуал "
        "(очищение, основной уход, увлажнение, SPF); 🌙 Вечерний ритуал (очищение, основной актив или сыворотка, "
        "восстановление и увлажнение); ✨ Подходящие компоненты (2–3); 🧴 На что обратить внимание при выборе косметики; "
        "🤍 Маленький совет. Предлагай категории средств, не выдумывай конкретные бренды и товары. "
        "Объясни постепенное введение новых средств и патч-тест. "
        "Запрещено использовать списки со звёздочками (* пункт). Вместо маркерных точек используй тематические эмодзи "
        "в начале строк: 💧, 🌿, ☀️, 🌙, ✨, 🧴. Текст должен быть эстетичным, с абзацами и выделением ключевых активов "
        "жирным шрифтом, без markdown-маркеров списков.\n\nОтветы пользователя:\n" + details
    )



@care_router.callback_query(F.data == "care:open")
async def open_care_from_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await start_care_checkout(callback, state)


@care_router.callback_query(F.data.startswith("care:mode:"))
async def choose_care_mode(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data or callback.message is None:
        await callback.answer()
        return
    bits = callback.data.split(":")
    if len(bits) != 4 or bits[2] not in {"photo", "quiz"}:
        await callback.answer("Не удалось определить режим", show_alert=True)
        return
    mode, order_id = bits[2], bits[3]
    user_id = callback.from_user.id
    if not await asyncio.to_thread(has_care_access_sync, user_id):
        await callback.answer("Сначала нужна подтверждённая оплата", show_alert=True)
        return
    order = await asyncio.to_thread(get_care_order_sync, order_id, user_id)
    if not order or order.get("status") != "succeeded":
        await callback.answer("Заказ не найден", show_alert=True)
        return
    if not await asyncio.to_thread(set_care_order_mode_sync, order_id, user_id, mode):
        await callback.answer("Не удалось сохранить выбор", show_alert=True)
        return
    await callback.answer()
    await _delete_callback_message(callback)
    await state.clear()
    await state.update_data(order_id=order_id, chosen_mode=mode)
    if mode == "photo":
        has_consent = await asyncio.to_thread(has_care_photo_consent_sync, user_id)
        if has_consent:
            # Carry the profile-level consent onto this order so photo validation is consistent.
            await asyncio.to_thread(record_care_photo_consent_sync, order_id, user_id)
            await _ask_care_photo_category(callback.message, state, order_id)
        else:
            await state.set_state(CareStates.waiting_for_consent)
            await callback.message.answer(
                "Перед началом важно твоё согласие 🤍\n\n"
                "Фото будет передано в Gemini API через подключённый сервис для автоматического анализа. "
                "Оно используется только для подготовки ответа: бот не сохраняет фотографию на постоянном диске. "
                "По фото можно описать лишь видимые особенности, это не медицинская диагностика.\n\n"
                "Согласна передать фото для обработки?",
                reply_markup=care_consent_keyboard(order_id),
            )
    else:
        await state.set_state(CareStates.survey_skin_type)
        await callback.message.answer(
            "Вопрос 1 из 3. Какой у тебя тип кожи? 🌸",
            reply_markup=care_quiz_keyboard("skin", order_id),
        )


@care_router.callback_query(F.data.startswith("care:consent:yes:"))
async def accept_care_photo_consent(callback: CallbackQuery, state: FSMContext) -> None:
    order_id = (callback.data or "").rsplit(":", 1)[-1]
    user_id = callback.from_user.id
    if not await asyncio.to_thread(has_care_access_sync, user_id):
        await callback.answer("Доступ не найден", show_alert=True)
        return
    ok = await asyncio.to_thread(record_care_photo_consent_sync, order_id, user_id)
    if not ok:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    await callback.answer()
    await _delete_callback_message(callback)
    await state.clear()
    await state.update_data(order_id=order_id, chosen_mode="photo")
    if callback.message:
        await _ask_care_photo_category(callback.message, state, order_id)


@care_router.callback_query(F.data.startswith("care:back:mode:"))
async def back_to_care_mode(callback: CallbackQuery, state: FSMContext) -> None:
    order_id = (callback.data or "").rsplit(":", 1)[-1]
    if not await asyncio.to_thread(has_care_access_sync, callback.from_user.id):
        await callback.answer("Доступ не найден", show_alert=True)
        return
    await callback.answer()
    await _delete_callback_message(callback)
    await state.clear()
    await state.set_state(CareStates.waiting_for_mode)
    if callback.message:
        await callback.message.answer(
            "Как тебе удобнее подобрать уход? 🌸",
            reply_markup=care_mode_keyboard(order_id),
        )


@care_router.callback_query(F.data.startswith("care:photo_category:"))
async def choose_care_photo_category(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data or callback.message is None:
        await callback.answer()
        return
    bits = callback.data.split(":")
    if len(bits) != 4:
        await callback.answer("Не удалось распознать выбор", show_alert=True)
        return
    _, _, category, order_id = bits
    categories = {
        "natural": "Натуральные эко-линейки и растительные компоненты",
        "korean": "Корейский уход и современные активы",
        "pharmacy": "Аптечная дерматокосметика и базовый комфорт",
        "mix": "Не принципиально, микс подходов",
    }
    if category not in categories:
        await callback.answer("Такого варианта нет", show_alert=True)
        return
    user_id = callback.from_user.id
    if not await asyncio.to_thread(has_care_access_sync, user_id):
        await callback.answer("Доступ не найден", show_alert=True)
        return
    if not await asyncio.to_thread(has_care_photo_consent_sync, user_id):
        await callback.answer("Сначала подтверди согласие на обработку фото", show_alert=True)
        return
    if not await asyncio.to_thread(update_care_order_answers_sync, order_id, user_id, {"photo_cosmetics_category": categories[category]}):
        await callback.answer("Не удалось сохранить выбор", show_alert=True)
        return
    await callback.answer()
    await _delete_callback_message(callback)
    await state.update_data(order_id=order_id, chosen_mode="photo", photo_cosmetics_category=categories[category])
    await state.set_state(CareStates.waiting_for_photo)
    await callback.message.answer(
        "Пришли одно чёткое фото лица при дневном освещении 🌸\n\n"
        "Лучше без плотного макияжа, фильтров и сильной обработки. "
        "Фото нужно только для предварительной оценки видимых особенностей кожи."
    )


@care_router.callback_query(F.data.startswith("care:quiz:"))
async def answer_care_quiz(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data or callback.message is None:
        await callback.answer()
        return
    bits = callback.data.split(":")
    if len(bits) != 5:
        await callback.answer("Не удалось распознать ответ", show_alert=True)
        return
    _, _, question, value, order_id = bits
    user_id = callback.from_user.id
    allowed = {
        "skin": {"dry": "Сухая / тонкая", "combo": "Нормальная / комбинированная",
                 "oily": "Жирная / пористая", "unknown": "Не знаю точно"},
        "concern": {"dryness": "Сухость и шелушения", "pores": "Поры, чёрные точки, блеск",
                    "dull": "Тусклый цвет, следы усталости", "tone": "Тонус, мелкие морщинки",
                    "sensitive": "Чувствительность и дискомфорт"},
        "brand": {"green": "Натуральные эко-линейки и растительные компоненты",
                  "korean": "Корейский уход и современные активы",
                  "pharmacy": "Аптека и базовый комфорт", "any": "Не принципиально, подбери сама"},
    }
    if question not in allowed or value not in allowed[question]:
        await callback.answer("Такого варианта нет", show_alert=True)
        return
    if not await asyncio.to_thread(has_care_access_sync, user_id):
        await callback.answer("Доступ не найден", show_alert=True)
        return
    field = {"skin": "skin_type", "concern": "concern", "brand": "brand_pref"}[question]
    if not await asyncio.to_thread(update_care_order_answers_sync, order_id, user_id, {field: allowed[question][value]}):
        await callback.answer("Не удалось сохранить ответ", show_alert=True)
        return
    await callback.answer()
    await _delete_callback_message(callback)
    await state.update_data(order_id=order_id, chosen_mode="quiz")
    if question == "skin":
        await state.set_state(CareStates.survey_concern)
        await callback.message.answer(
            "Вопрос 2 из 3. Что хотелось бы улучшить? ✨",
            reply_markup=care_quiz_keyboard("concern", order_id),
        )
    elif question == "concern":
        await state.set_state(CareStates.survey_brand_pref)
        await callback.message.answer(
            "Вопрос 3 из 3. Какой уход тебе ближе? 🌿",
            reply_markup=care_quiz_keyboard("brand", order_id),
        )
    else:
        await state.set_state(CareStates.generating_result)
        order = await asyncio.to_thread(get_care_order_sync, order_id, user_id)
        answers = (order or {}).get("answers", {})
        await send_care_result(callback.message, order_id, user_id, _quiz_prompt(answers))
        await state.clear()


@care_router.callback_query(F.data.startswith("care:repeat:"))
async def repeat_care_result(callback: CallbackQuery, state: FSMContext) -> None:
    order_id = (callback.data or "").rsplit(":", 1)[-1]
    user_id = callback.from_user.id
    if not await asyncio.to_thread(has_care_access_sync, user_id):
        await callback.answer("Доступ не найден", show_alert=True)
        return
    order = await asyncio.to_thread(get_care_order_sync, order_id, user_id)
    if not order or order.get("status") != "succeeded":
        await callback.answer("Заказ не найден", show_alert=True)
        return
    await callback.answer()
    await _delete_callback_message(callback)
    await state.clear()
    await state.update_data(order_id=order_id, chosen_mode=order.get("mode"))
    if order.get("mode") == "photo":
        has_consent = await asyncio.to_thread(has_care_photo_consent_sync, user_id)
        if has_consent:
            # Carry the profile-level consent onto this repeated order as well.
            await asyncio.to_thread(record_care_photo_consent_sync, order_id, user_id)
            await _ask_care_photo_category(callback.message, state, order_id)
        else:
            await state.set_state(CareStates.waiting_for_consent)
            await callback.message.answer(
                "Перед началом важно твоё согласие 🤍\n\n"
                "Фото будет передано в Gemini API через подключённый сервис только для подготовки ответа. "
                "Бот не сохраняет фотографию на постоянном диске. Согласна продолжить?",
                reply_markup=care_consent_keyboard(order_id),
            )
    else:
        await state.set_state(CareStates.generating_result)
        await send_care_result(
            callback.message, order_id, user_id,
            _quiz_prompt(order.get("answers") or {}),
        )
        await state.clear()


async def process_care_photo(message: Message, state: FSMContext) -> bool:
    """Called by main.py's existing photo handler; returns True when consumed."""
    current = await state.get_state()
    if current != CareStates.waiting_for_photo.state:
        return False
    data = await state.get_data()
    order_id = data.get("order_id")
    user_id = message.from_user.id if message.from_user else 0
    if not order_id or not await asyncio.to_thread(has_care_access_sync, user_id):
        await message.answer("Не удалось проверить доступ. Открой «Моё сияние» и выбери уход ещё раз 🌿")
        await state.clear()
        return True
    order = await asyncio.to_thread(get_care_order_sync, order_id, user_id)
    if not order or not order.get("status") == "succeeded":
        await message.answer("Оплаченный заказ не найден. Напиши в поддержку, пожалуйста.")
        await state.clear()
        return True
    if not order.get("mode") == "photo":
        await message.answer("Сейчас выбран другой режим. Открой подбор ухода ещё раз 🌸")
        await state.clear()
        return True
    if not order.get("photo_consent_at"):
        await message.answer("Сначала подтверди согласие на обработку фото кнопкой выше 🌸")
        await state.set_state(CareStates.waiting_for_consent)
        await message.answer("Фото передаётся в Gemini API для анализа. Согласна продолжить?", reply_markup=care_consent_keyboard(order_id))
        return True
    if not message.photo:
        await message.answer("Пришли, пожалуйста, фотографию как изображение 🌸")
        return True
    try:
        file_info = await _bot.get_file(message.photo[-1].file_id)
        if file_info.file_size and file_info.file_size > 10 * 1024 * 1024:
            await message.answer("Фото слишком большое. Пришли изображение размером до 10 МБ 🌿")
            return True
        buffer = io.BytesIO()
        await _bot.download(message.photo[-1], destination=buffer)
        image_bytes = buffer.getvalue()
        buffer.close()
        if not image_bytes or len(image_bytes) > 10 * 1024 * 1024:
            await message.answer("Не удалось прочитать фото. Попробуй отправить его ещё раз 🌿")
            return True
        await state.set_state(CareStates.generating_result)
        category = (order.get("answers") or {}).get("photo_cosmetics_category")
        if not category:
            await _ask_care_photo_category(message, state, order_id)
            return True
        await send_care_result(message, order_id, user_id, _photo_prompt(category), image_bytes=image_bytes)
        del image_bytes
        await state.clear()
        return True
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception("Care photo processing error: %s", error)
        await message.answer(
            "Не получилось обработать фото. Оплата сохранена — попробуй ещё раз, повторно платить не нужно 🌸",
            reply_markup=care_result_keyboard(order_id),
        )
        return True



async def process_care_text(message: Message, state: FSMContext) -> bool:
    """Keep free text from escaping an active button/photo step into general chat."""
    current = await state.get_state()
    data = await state.get_data()
    order_id = data.get("order_id")
    if current == CareStates.waiting_for_mode.state and order_id:
        await message.answer("Выбери один из двух способов кнопкой 🌸", reply_markup=care_mode_keyboard(order_id))
        return True
    if current == CareStates.waiting_for_payment.state:
        await message.answer("Сначала заверши оплату по ссылке ЮKassa. Если ссылка потерялась, снова открой «Подобрать уход и косметику» 🌿")
        return True
    if current == CareStates.waiting_for_consent.state and order_id:
        await message.answer("Нажми кнопку согласия или вернись к выбору режима 🤍", reply_markup=care_consent_keyboard(order_id))
        return True
    if current == CareStates.waiting_for_photo_category.state and order_id:
        await message.answer("Сначала выбери категорию ухода кнопкой 🌸", reply_markup=care_photo_category_keyboard(order_id))
        return True
    if current == CareStates.waiting_for_photo.state:
        await message.answer("Жду одно чёткое фото лица при дневном освещении 🌸")
        return True
    if current == CareStates.survey_skin_type.state and order_id:
        await message.answer("Выбери тип кожи кнопкой 👇", reply_markup=care_quiz_keyboard("skin", order_id))
        return True
    if current == CareStates.survey_concern.state and order_id:
        await message.answer("Выбери, что хочется улучшить 👇", reply_markup=care_quiz_keyboard("concern", order_id))
        return True
    if current == CareStates.survey_brand_pref.state and order_id:
        await message.answer("Выбери предпочтительный уход 👇", reply_markup=care_quiz_keyboard("brand", order_id))
        return True
    if current == CareStates.generating_result.state:
        await message.answer("Уже собираю рекомендации — секундочку 🌸")
        return True
    return False
