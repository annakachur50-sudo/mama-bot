"""Paid AI skincare flow for Mama 24/7.

The module reuses the bot's configured Gemini client and the existing YooKassa
payment integration. Photos are downloaded to memory only and never persisted.
"""
from __future__ import annotations

import asyncio
import html
import io
import json
import logging
import re
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
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

REF_LINK_GREENWAY = "https://greenwayglobal.com/shop?gw=etJ4vRkF8D"
REF_LINK_SW = (
    "https://ru.siberianhealth.com/ru/shop/user/registration/"
    "PRIVILEGED_CLIENT/?referral=2539466720"
)
REFERRAL_BRANDS = {"Greenway", "Siberian Wellness"}
ALLOWED_BRANDS = REFERRAL_BRANDS
ECO_ALLOWED_TERMS = (
    "Greenway", "Cactus", "Happy Dew", "Anny Rey", "Nice Code", "Sharme Minerals",
    "Siberian Wellness", "Experalta Biomelle", "Chronolong", "Experalta Platinum",
    "бакучиол", "10% ниацинамид", "Siberian Code", "Endemix",
)
ECO_FORBIDDEN_BRANDS = (
    "Greenway Hemp", "Anua", "Manyo", "Round Lab", "Medicube",
    "La Roche-Posay", "CeraVe", "Art&Fact", "Icon Skin",
)


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
        ("🌿 Натуральные эко-линейки и травы", "n"),
        ("✨ Корейский уход и современные активы", "k"),
        ("🧴 Аптека и базовый комфорт", "p"),
        ("💛 Не принципиально / Микс", "m"),
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


def care_result_keyboard(order_id: str, recommended_brands: list[str] | None = None) -> InlineKeyboardMarkup:
    recommended = set(recommended_brands or [])
    referral_row = []
    if "Greenway" in recommended:
        referral_row.append(InlineKeyboardButton(text="🌿 Заказать уход Greenway", url=REF_LINK_GREENWAY))
    if "Siberian Wellness" in recommended:
        referral_row.append(InlineKeyboardButton(text="💎 Продукты Siberian Wellness", url=REF_LINK_SW))
    rows = [referral_row] if referral_row else []
    rows.append([
        InlineKeyboardButton(text="🔄 Повторить подбор", callback_data=f"care:repeat:{order_id}"),
        InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _brand_is_positive_recommendation(answer: str, brand: str) -> bool:
    """Reject an explicit negative mention without misreading unrelated warnings on the same line."""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", answer)
    negative = re.compile(
        r"(?:"
        + re.escape(brand)
        + r"\s+не\s+(?:подходит|рекомендую|советую|используй|выбирай)"
        + r"|не\s+(?:подходит|рекомендую|советую|используй|выбирай)\s+(?:бренд\s+)?"
        + re.escape(brand)
        + r")",
        re.IGNORECASE,
    )
    mentions = [sentence for sentence in sentences if brand.casefold() in sentence.casefold()]
    return bool(mentions) and any(not negative.search(sentence) for sentence in mentions)


def _parse_care_response(raw: str, cosmetics_category: str | None = None) -> tuple[str, list[str]]:
    """Parse Gemini JSON safely; malformed structures never produce referral buttons."""
    text = (raw or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        # Safe fallback: preserve readable text, but never infer structured links.
        fallback = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
        return fallback, []
    if not isinstance(payload, dict) or not isinstance(payload.get("answer"), str):
        return text, []
    answer = payload["answer"].strip()
    if not answer:
        return "", []
    eco = _is_eco_category(cosmetics_category)
    if eco and _contains_forbidden_eco_brand(answer):
        logger.warning("Rejected non-eco brand mention in eco care response")
        return ("Не удалось безопасно сформировать рекомендации строго в выбранной эко-категории. "
                "Попробуй повторить подбор чуть позже 🌿"), []
    brands = payload.get("recommended_brands")
    if not isinstance(brands, list):
        return answer, []
    valid = []
    for brand in brands:
        if (
            isinstance(brand, str)
            and brand in REFERRAL_BRANDS
            and _brand_is_positive_recommendation(answer, brand)
            and brand not in valid
        ):
            valid.append(brand)
    return answer, valid


def _is_eco_category(category: str | None) -> bool:
    value = (category or "").casefold()
    return any(token in value for token in ("эко", "натураль", "раститель", "green"))


def _contains_forbidden_eco_brand(answer: str) -> bool:
    return any(re.search(r"(?<!\w)" + re.escape(brand) + r"(?!\w)", answer, re.IGNORECASE)
               for brand in ECO_FORBIDDEN_BRANDS)

async def _delete_callback_message(callback: CallbackQuery) -> None:
    """Remove a consumed inline-keyboard message without interrupting the flow."""
    if callback.message is None:
        return
    try:
        await callback.message.delete()
    except TelegramBadRequest as error:
        # Includes Telegram's "message to delete not found" / "message can't be deleted" responses.
        logger.debug("Telegram rejected care message deletion: %s", error)
    except Exception as error:
        # Unexpected deletion failures must not interrupt the flow.
        # The next step should still be delivered so the user is never stuck.
        logger.debug("Could not delete care step message: %s", error)



def _format_result(value: str) -> str:
    safe = html.escape(value.strip(), quote=False)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe, flags=re.DOTALL)
    safe = safe.replace("**", "")
    return safe.replace("*", "")


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
                           image_bytes: bytes | None = None,
                           cosmetics_category: str | None = None) -> None:
    if _client is None:
        await message.answer("Анализ временно недоступен. Попробуй ещё раз чуть позже 🌿")
        return
    await asyncio.to_thread(mark_care_result_status_sync, order_id, user_id, "processing")
    status = await message.answer(
        "Изучаю текстуру кожи... ✨" if image_bytes is not None
        else "🌸 Подбираю уход и собираю рекомендации…"
    )
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
        raw_result = (response.text or "").strip()
        if not raw_result:
            raise RuntimeError("Gemini returned an empty care result")
        result, recommended_brands = _parse_care_response(raw_result, cosmetics_category)
        if not result:
            raise RuntimeError("Gemini returned a care response without answer text")
        await asyncio.to_thread(save_care_result_sync, order_id, user_id, result)
        formatted = _format_result(result)
        if recommended_brands:
            formatted += (
                "\n\nНекоторые ссылки могут быть реферальными. "
                "Это не влияет на стоимость товаров для тебя."
            )
        chunks = _split_text(formatted)
        for index, chunk in enumerate(chunks):
            await message.answer(
                chunk,
                reply_markup=care_result_keyboard(order_id, recommended_brands)
                if index == len(chunks) - 1 else None,
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


def _product_matrix_prompt(cosmetics_category: str) -> str:
    """Return exactly one isolated product matrix for the user's selected category."""
    category = (cosmetics_category or "").casefold()
    if _is_eco_category(category):
        return (
            "ИЗОЛИРОВАННАЯ ЭКО-МАТРИЦА. Используй исключительно эти линейки и бренды: "
            "Greenway: Cactus, Happy Dew, Anny Rey, Nice Code, Sharme Minerals. "
            "Greenway Hemp строго запрещён: не упоминай его ни в каком контексте. "
            "Siberian Wellness: Experalta Biomelle, Chronolong, Experalta Platinum "
            "(бакучиол, 10% ниацинамид), Siberian Code, Endemix. "
            "Любые другие бренды и линейки запрещены. Не упоминай и не сравнивай корейскую косметику, "
            "аптечную дерматокосметику или масс-маркет. Если подходящего средства в этой матрице нет, "
            "опиши категорию средства без стороннего бренда. Не выдумывай продукты, составы и свойства. "
            "Верни JSON с answer и recommended_brands. В recommended_brands разрешены только "
            "Greenway и Siberian Wellness, если они позитивно рекомендованы в answer; иначе []."
        )
    if any(token in category for token in ("корей", "korean", "актив")):
        return (
            "ИЗОЛИРОВАННАЯ МАТРИЦА КОРЕЙСКОГО УХОДА: Anua, Manyo Pure Cleansing Oil, "
            "Round Lab 1025 Dokdo, Medicube. Другие каталоги не упоминай. "
            "recommended_brands всегда [] для этой категории."
        )
    if any(token in category for token in ("аптек", "pharmacy", "базов")):
        return (
            "ИЗОЛИРОВАННАЯ АПТЕЧНАЯ МАТРИЦА: La Roche-Posay Cicaplast B5+, Toleriane, Effaclar; "
            "CeraVe. Другие каталоги не упоминай. recommended_brands всегда []."
        )
    return (
        "ИЗОЛИРОВАННАЯ МАТРИЦА МИКС: Greenway Cactus, Happy Dew, Anny Rey, Nice Code, "
        "Sharme Minerals; Siberian Wellness Experalta Biomelle, Chronolong, Experalta Platinum, "
        "Siberian Code, Endemix; Anua, Manyo Pure Cleansing Oil, Round Lab 1025 Dokdo, Medicube; "
        "La Roche-Posay, CeraVe, Art&Fact, Icon Skin. Greenway Hemp запрещён. "
        "Используй только подходящие подтверждённые позиции, не выдумывай продукты. "
        "recommended_brands может содержать только Greenway и/или Siberian Wellness."
    )


def _photo_prompt(cosmetics_category: str) -> str:
    return (
        "Ты — бережный ИИ-помощник по уходу за кожей. Анализируй только видимые особенности на фото. "
        "Освещение, камера, фильтры и макияж могут искажать картину. Если качество фото недостаточное, "
        "честно сообщи об этом и не придумывай признаки. Не диагностируй заболевания, не назначай препараты, "
        "не обещай лечение или гарантированный эффект. Составь персональный план на русском, на «ты», "
        "дружелюбно и без медицинского жаргона. Внутри answer не используй markdown-звёздочки или markdown-списки. " + "Начни с «🌸 ТВОЙ ПЕРСОНАЛЬНЫЙ УХОД». "
        "Учитывай предпочтение пользователя: " + cosmetics_category + ". "
        "Структура answer: что учитываем; ☀️ утренний ритуал; 🌙 вечерний ритуал; подходящие компоненты; "
        "предостережения по чувствительности и переносимости; 🤍 маленький совет. "
        "В подходящих этапах приводи 1–2 конкретных примера из разрешённой матрицы. "
        + _product_matrix_prompt(cosmetics_category)
    )


def _quiz_prompt(answers: dict[str, str]) -> str:
    labels = {
        "skin_type": "Тип кожи",
        "concern": "Что хочется улучшить",
        "brand_pref": "Предпочтения по уходу",
    }
    details = "\n".join(f"{labels.get(key, key)}: {value}" for key, value in answers.items())
    return (
        "Ты — бережный ИИ-помощник по уходу за кожей. Составь персональный базовый план только на основании "
        "ответов пользователя. Не выдумывай аллергию, заболевания, продукты и составы. При чувствительности "
        "или непереносимости предложи мягкий минималистичный уход. Не ставь диагнозы, не назначай препараты, "
        "не обещай лечение или гарантированный эффект. Ответ на русском, на «ты», дружелюбно и без медицинского "
        "жаргона. Начни с «🌸 ТВОЙ ПЕРСОНАЛЬНЫЙ УХОД». Структура answer: что учитываем; ☀️ утренний ритуал; "
        "🌙 вечерний ритуал; подходящие компоненты; предостережения; 🤍 маленький совет. "
        "В каждом уместном этапе приводи 1–2 точных примера из матрицы, не заполняй ненужные этапы. "
        "Не используй одновременно несколько сильных активов без необходимости. "
        + _product_matrix_prompt(answers.get("brand_pref", ""))
        + "\n\nОтветы пользователя:\n" + details
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
    # Acknowledge the tap immediately; database checks below may take noticeable time.
    await callback.answer()
    mode, order_id = bits[2], bits[3]
    user_id = callback.from_user.id
    if not await asyncio.to_thread(has_care_access_sync, user_id):
        await callback.message.answer("Сначала нужна подтверждённая оплата 🌿")
        return
    order = await asyncio.to_thread(get_care_order_sync, order_id, user_id)
    if not order or order.get("status") != "succeeded":
        await callback.message.answer("Оплаченный заказ не найден. Напиши в поддержку, пожалуйста.")
        return
    if not await asyncio.to_thread(set_care_order_mode_sync, order_id, user_id, mode):
        await callback.message.answer("Не удалось сохранить выбор. Попробуй ещё раз 🌿")
        return
    has_consent = False
    if mode == "photo":
        # Do all consent reads/writes before deleting the visible menu. If storage
        # is temporarily unavailable, the user can retry instead of being stranded.
        try:
            has_consent = await asyncio.to_thread(has_care_photo_consent_sync, user_id)
            if has_consent:
                consent_recorded = await asyncio.to_thread(
                    record_care_photo_consent_sync, order_id, user_id
                )
                if not consent_recorded:
                    raise RuntimeError("Could not carry photo consent to the current order")
        except Exception:
            logger.exception("Could not prepare care photo consent for order %s", order_id)
            await callback.message.answer(
                "Не получилось подготовить шаг с фотографией. Ничего не потерялось — "
                "нажми «Подобрать по фото» ещё раз чуть позже 🌿"
            )
            return

    await _delete_callback_message(callback)
    await state.clear()
    await state.update_data(order_id=order_id, chosen_mode=mode)
    if mode == "photo":
        if has_consent:
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
    # Acknowledge immediately so slow database work cannot make the button appear dead.
    await callback.answer()
    if not await asyncio.to_thread(has_care_access_sync, user_id):
        if callback.message:
            await callback.message.answer("Доступ не найден 🌿")
        return
    ok = await asyncio.to_thread(record_care_photo_consent_sync, order_id, user_id)
    if not ok:
        if callback.message:
            await callback.message.answer("Заказ не найден 🌿")
        return
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
        "n": "Натуральные эко-линейки и растительные компоненты",
        "k": "Корейский уход и современные активы",
        "p": "Аптечная дерматокосметика и базовый комфорт",
        "m": "Не принципиально, микс подходов",
    }
    if category not in categories:
        await callback.answer("Такого варианта нет", show_alert=True)
        return
    user_id = callback.from_user.id
    # Acknowledge before any database round-trips; the invitation is sent below
    # as a fresh chat message after the inline menu is consumed.
    await callback.answer()
    if not await asyncio.to_thread(has_care_access_sync, user_id):
        await callback.message.answer("Доступ не найден 🌿")
        return
    if not await asyncio.to_thread(has_care_photo_consent_sync, user_id):
        await callback.message.answer("Сначала подтверди согласие на обработку фото 🤍")
        return
    if not await asyncio.to_thread(update_care_order_answers_sync, order_id, user_id, {"photo_cosmetics_category": categories[category]}):
        await callback.message.answer("Не удалось сохранить выбор. Попробуй ещё раз 🌿")
        return
    await _delete_callback_message(callback)
    await state.update_data(order_id=order_id, chosen_mode="photo", photo_cosmetics_category=categories[category])
    await state.set_state(CareStates.waiting_for_photo)
    # This is a new message, not the consumed inline-keyboard message above:
    # keep it visible so the user can send the selfie in the active FSM state.
    await callback.message.answer(
        "📸 <b>Пришли мне одно чёткое селфи</b> лица крупным планом при дневном свете "
        "(без плотного тонального крема и фильтров). Я бережно оценю текстуру пор, "
        "тон и уровень увлажнённости ✨",
        parse_mode="HTML",
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
    image_bytes = None
    try:
        # Show activity while Telegram downloads the image and Gemini prepares the analysis.
        await _bot.send_chat_action(chat_id=message.chat.id, action="typing")
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
        await _bot.send_chat_action(chat_id=message.chat.id, action="typing")
        await send_care_result(message, order_id, user_id, _photo_prompt(category),
                                  image_bytes=image_bytes, cosmetics_category=category)
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
    finally:
        image_bytes = None
        if "buffer" in locals():
            buffer.close()



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
        await message.answer("📸 Пожалуйста, отправь именно фотографию лица крупным планом, чтобы я могла оценить состояние кожи.")
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
