import asyncio
import html
import logging
import os
from aiohttp import web
import time

import random
import re
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
TELEGRAM_MESSAGE_LIMIT = 4096
TELEGRAM_CHUNK_SIZE = TELEGRAM_MESSAGE_LIMIT - 256
MAX_HISTORY_MESSAGES = 20
STATE_DB_PATH = os.path.join(os.path.dirname(__file__), "bot_state.sqlite3")
THINKING_MESSAGES = (
    "Завариваю чаёк и думаю... ☕️",
    "Секундочку, уже спешу с ответом... 💭",
    "Настраиваюсь на твою волну... ✨",
    "Слушаю тебя внимательно, минутку... 🌸",
    "Сейчас всё разложим по полочкам... 🌿",
)
VOICE_REPLY_INSTRUCTION = (
    "Прослушай голосовое сообщение пользователя и ответь на него по-русски, "
    "учитывая предыдущий контекст беседы."
)
START_MESSAGE = (
    "Привет, дорогая! 🌸\n"
    "Меня зовут Аня. Я мама троих деток и прекрасно знаю, что такое мамские будни: "
    "когда в голове тысяча дел, ужин сам себя не сварит, а сил иногда остаётся "
    "только на то, чтобы доползти до кровати.\n\n"
    "Я создала этого помощника как тёплую подругу, которая всегда под рукой. Здесь можно:\n"
    "🍲 Быстро придумать простой обед или ужин из того, что есть в холодильнике\n"
    "🧹 Разгрести домашний хаос за 15 минут без надрыва\n"
    "💖 Получить тёплую поддержку и выдохнуть, когда накатило\n\n"
    "Ты можешь просто нажимать кнопки внизу или наговорить мне голосовое — "
    "я рядом 24/7. Как твои дела сегодня?"
)
MENU_BUTTONS = (
    "🍲 Накормить семью",
    "📦 Разгрести хаос",
    "📅 День по полочкам",
    "💖 Тёплая поддержка",
)
BOT_COMMANDS = [
    BotCommand(command="start", description="Главное меню и старт"),
    BotCommand(command="reset_me", description="Стереть мои данные"),
]
SYSTEM_PROMPT = """Ты — виртуальная подруга и заботливая помощница для мам «Мама 24/7».
Общайся тепло, легко, искренне, «на ты», с добрым юмором и поддержкой ☕️🌸.

Правила подачи текста:
- Обязательно используй эмодзи (в меру, чтобы текст дышал уютом и радостью) ✨🌿.
- Разделяй текст на короткие, удобные абзацы (не пиши простынями, маме с телефона должно быть легко читать).
- Важные мысли или акценты выделяй **жирным шрифтом**.
- Если известно имя пользователя, периодически обращайся по имени — мягко и по-дружески (не в каждой строчке, но чтобы чувствовалось личное тепло).

Правила по сценариям:
- «🍲 Накормить семью»: простые, быстрые, аппетитные семейные рецепты за 20–30 минут из того, что под рукой.
- «📦 Разгрести хаос»: экспресс-уборка за 5–15 минут БЕЗ едкой химии и БЕЗ дедовских методов (никакой соды, уксуса и горчичного порошка!). Рекомендуй эстетичный эко-подход в стиле Greenway: салфетки и файберы из микроволокна (работают от одной воды, убирают жир и грязь без капли химии), натуральную очищающую пасту или кислородный эко-очиститель для сложных пятен.
- «📅 День по полочкам»: понятный, спокойный план без гонки, с обязательным пунктом «время для себя и чашечка кофе/чая» ☕️.
- «💖 Тёплая поддержка»: искренние слова заботы, напоминание, что мама умница и всё делает правильно.

В ответах сразу переходи к делу без шаблонных формальных вступлений.

ЭКСПЕРТНАЯ ЭКО-МАТРИЦА И ПРАВИЛА РЕКОМЕНДАЦИЙ (GREENWAY GLOBAL):
Ты выступаешь как чуткая, знающая подруга-эксперт. Ты НЕ навязываешь покупки в каждом сообщении.
Ты даёшь сначала 100% глубокий, полезный ответ на вопрос мамы, и ТОЛЬКО при наличии четкого повода (триггера) добавляешь ОДНУ мягкую органичную рекомендацию со ссылкой.

ОФИЦИАЛЬНАЯ ССЫЛКА НА ИНТЕРНЕТ-МАГАЗИН:
https://greenwayglobal.com/shop?gw=etJ4vRkF8D

МАТРИЦА ТОЧНЫХ РЕШЕНИЙ:
1. ТЕМА: ЭКСПРЕСС-УБОРКА, ДОМ, ПОРЯДОК БЕЗ ХИМИИ:
   - Трудные пятна на детском (ягоды, соки, пюре, трава): натуральное эко-мыло для стирки BioTrim (отбеливающее или против пятен), спрей-пятновыводитель BioTrim или замачивание в очищающем порошке Mystik в горячей воде. (НЕ предлагай стирать въевшиеся пятна просто пластинами!).
   - Безопасная регулярная стирка детского и взрослого белья: растворимые эко-пластины BioTrim (гипоаллергенно, без фосфатов и едкой пыли).
   - Жир, нагар, духовка, сковороды, белая подошва обуви: очищающая паста или порошок Mystik + диск Green Fiber Инволвер.
   - Окна, зеркала, фасады без химии: файбер для стекла Green Fiber (работает только с водой, без разводов).
   - Мытье посуды без химии: файбер для посуды Green Fiber.

2. ТЕМА: ЭНЕРГИЯ, РЕСУРС, УСТАЛОСТЬ И БИОХАКИНГ:
   - Недосып, «туман» в голове, забывчивость, стресс: комплексы биохакинга Neuroera (Brain Active / Brain Energy), Welllab Магний B6 или капли Welllab Liquid (фульвовые кислоты, Экосорб).
   - Утренние отеки, тяжесть, застой лимфы: дренажный напиток Balancer Drain Maxi.
   - Упадок сил к вечеру, тревожность, выгорание: напиток Balancer Good Night или чаи коллекций TeaVitall для баланса нервной системы.

3. ТЕМА: ПИТАНИЕ НА БЕГУ (БАЛАНСЕР):
   - Мама не успевает поесть, кусочничает, нет сил готовить себе: функциональные коктейли Balancer (быстрый белок и витамины за 1 минуту), горячие крем-супы Balancer, полезная клетчатка Bio-Topping.

4. ТЕМА: КРАСОТА, СВЕЖИЙ ВИД ЗА 3 МИНУТЫ И ЗАБОТА О СЕБЕ:
   - Свежий макияж на прогулку/быстро убрать следы усталости: декоративная линейка Foet — консилер под глаза, фиксирующий гель для бровей, проявляющийся pH-бальзам для губ Foet (подстраивается под тон губ, освежает лицо) или матовая/сатиновая помада.
   - Ощущение женственности, аромат для настроения: селективный парфюм Enjoy Care.
   - Уход за лицом и телом: линейка Anny Rey, Sharme Minerals, гидрогелевые патчи под глаза.

ПРАВИЛО ОФОРМЛЕНИЯ ССЫЛКИ В ТЕКСТЕ:
Формулируй рекомендацию ласково и естественно, вставляя ссылку в формате markdown:
Пример: «Кстати, чтобы не тереть духовку часами и не дышать химией, очень спасает паста Mystik с диском Инволвер. Я всё это заказываю в официальном эко-магазине [вот тут](https://greenwayglobal.com/shop?gw=etJ4vRkF8D) 🌿»"""
MENU_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=MENU_BUTTONS[0]), KeyboardButton(text=MENU_BUTTONS[1])],
        [KeyboardButton(text=MENU_BUTTONS[2]), KeyboardButton(text=MENU_BUTTONS[3])],
    ],
    resize_keyboard=True,
    is_persistent=False,
    input_field_placeholder="Выбери, чем помочь",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("telegram-gemini-bot")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing required secret: TELEGRAM_BOT_TOKEN")
if not GOOGLE_API_KEY:
    raise RuntimeError("Missing required secret: GOOGLE_API_KEY")

client = genai.Client(
    api_key=GOOGLE_API_KEY,
    http_options={"base_url": "https://api.proxyapi.ru/google"}
)
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dispatcher = Dispatcher()

user_names: dict[int, str] = {}
pending_details: dict[int, str] = {}
conversation_history_by_user: dict[int, list[types.Content]] = {}
user_request_locks: dict[int, asyncio.Lock] = {}
def append_history(user_id: int, user_content: types.Content, model_text: str) -> None:
    history = conversation_history_by_user.setdefault(user_id, [])
    history.append(user_content)
    history.append(
        types.Content(
            role="model",
            parts=[types.Part.from_text(text=model_text)],
        )
    )
    if len(history) > 20:
        conversation_history_by_user[user_id] = history[-20:]


def initialize_user_state() -> None:
    global user_names

    with sqlite3.connect(STATE_DB_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_names (
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            )
            """
        )
        name_rows = connection.execute(
            "SELECT user_id, name FROM user_names"
        ).fetchall()
    user_names = {int(user_id): name for user_id, name in name_rows}


def delete_user_data_from_database(user_id: int) -> None:
    user_data_tables = ("user_names", "pending_user_names", "welcomed_users")
    with sqlite3.connect(STATE_DB_PATH) as connection:
        existing_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        for table_name in user_data_tables:
            if table_name in existing_tables:
                connection.execute(
                    f'DELETE FROM "{table_name}" WHERE user_id = ?',
                    (user_id,),
                )


HEADER_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
BULLET_PATTERN = re.compile(r"^\s*[-*+•‣▪◦●○◆▫➤→]\ufe0f?\s+(.+?)\s*$")
NUMBERED_LIST_PATTERN = re.compile(r"^\s*(\d+)[.)]\s+(.+?)\s*$")
BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")
LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)")

def format_inline_markdown(text: str) -> str:
    # 1. Сначала превращаем markdown-ссылки во временную заглушку или обрабатываем после escape:
    escaped = html.escape(text, quote=False)
    # Возвращаем жирный шрифт
    formatted = BOLD_PATTERN.sub(r"<b>\1</b>", escaped)
    # Превращаем [текст](url) в кликабельную ссылку <a href="url">текст</a>
    formatted = LINK_PATTERN.sub(r'<a href="\2">\1</a>', formatted)
    return formatted.replace("*", "")


def format_telegram_html(text: str) -> str:
    formatted_lines = []

    for line in text.splitlines():
        header = HEADER_PATTERN.match(line)
        if header:
            heading = BOLD_PATTERN.sub(r"\1", header.group(1)).replace("*", "")
            formatted_lines.append(f"<b>{html.escape(heading.strip(), quote=False)}</b>")
            continue

        bullet = BULLET_PATTERN.match(line)
        if bullet:
            formatted_lines.append(f"• {format_inline_markdown(bullet.group(1))}")
            continue

        numbered_item = NUMBERED_LIST_PATTERN.match(line)
        if numbered_item:
            number, item = numbered_item.groups()
            formatted_lines.append(f"{number}. {format_inline_markdown(item)}")
            continue

        formatted_lines.append(format_inline_markdown(line))

    return "\n".join(formatted_lines).replace("*", "")


def split_response(text: str, limit: int = TELEGRAM_CHUNK_SIZE) -> list[str]:
    chunks = []
    current_lines = []
    current_length = 0

    for line in text.splitlines():
        if len(line) > limit:
            if current_lines:
                chunks.append("\n".join(current_lines))
                current_lines = []
                current_length = 0

            fragments = [
                line[start : start + limit]
                for start in range(0, len(line), limit)
            ]
            chunks.extend(fragments[:-1])
            current_lines = [fragments[-1]]
            current_length = len(fragments[-1])
            continue

        added_length = len(line) + (1 if current_lines else 0)
        if current_lines and current_length + added_length > limit:
            chunks.append("\n".join(current_lines))
            current_lines = [line]
            current_length = len(line)
        else:
            current_lines.append(line)
            current_length += added_length

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks or [""]

ADMIN_ID = 5267406602
LOG_CHANNEL_ID = -1004353307194

@dispatcher.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if message.from_user is None or message.from_user.id != ADMIN_ID:
        return

    try:
        with sqlite3.connect(STATE_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(DISTINCT user_id) FROM user_names")
            total_users = cursor.fetchone()[0]

        await message.answer(f"Всего уникальных мам в боте: {total_users}")

    except Exception as err:
        logger.exception("Stats error: %s", err)
        await message.answer(f"Ошибка получения статистики: {err}")



@dispatcher.message(CommandStart())
async def handle_start(message: Message) -> None:
    if message.from_user is None:
        return

    user_id = message.from_user.id

    # Берём имя из Telegram и убираем лишнее, если там смайлы или цифры
    raw_name = (message.from_user.first_name or "").strip()
    clean_name = raw_name if raw_name.isalpha() and 2 <= len(raw_name) <= 20 else ""
    user_names[user_id] = clean_name

    try:
        with sqlite3.connect(STATE_DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_names (user_id, name) VALUES (?, ?)",
                (user_id, clean_name),
            )
    except Exception as err:
        logger.warning("Could not save start user: %s", err)

    try:
        user_tag = f"@{message.from_user.username}" if message.from_user.username else "без никнейма"
        await message.bot.send_message(
            -1004353307194,
            f"🌸 <b>Новая гостья в домике!</b>\n\n👤 Имя: <b>{clean_name}</b>\n🔗 Тег: {user_tag}\n🆔 ID: <code>{user_id}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as log_err:
        logger.warning("Could not send log to channel: %s", log_err)

    start_inline_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🍲 Что приготовить за 20 минут?", callback_data="start_cook")],
            [InlineKeyboardButton(text="📦 Расхламить хаос за 15 минут", callback_data="start_declutter")],
            [InlineKeyboardButton(text="💖 Мне тяжело, нужна поддержка", callback_data="start_support")],
        ]
    )

    greeting_text = (
        f"Привет, {clean_name}! 🌸\n\n"
        "Я Аня, мама троих деток. Прекрасно знаю мамские будни: в голове миллион задач, "
        "силы на нуле, а ужин сам себя не сварит.\n\n"
        "Я создала этого бота как тёплую подругу, чтобы за пару минут разгрузить твою голову. "
        "С чего начнём прямо сейчас? Выбирай кнопку 👇"
    )

    await message.answer(
        greeting_text,
        reply_markup=start_inline_kb,
        parse_mode=ParseMode.HTML,
    )

@dispatcher.callback_query(lambda c: c.data in ["start_cook", "start_declutter", "start_support"])
async def process_start_action(callback: CallbackQuery) -> None:
    await callback.answer()

    prompts_map = {
        "start_cook": "Что быстро приготовить на ужин для всей семьи за 20-30 минут из простых продуктов?",
        "start_declutter": "Дай простой экспресс-план, как разобрать домашний хаос за 15 минут без надрыва.",
        "start_support": "Мне сейчас тяжело, устала от быта и детей. Поддержи меня тепло, как подруга.",
    }

    selected_prompt = prompts_map.get(callback.data, "")
    if selected_prompt and callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await answer_with_gemini(callback.message, selected_prompt)

def personalized_system_prompt(user_name: str | None) -> str:
    user_greeting = (
        f"6. Собеседницу зовут {user_name}. Обращайся по имени легко и естественно, но не части и не ставь его в каждое предложение.\n"
        if user_name
        else "6. Обращайся к собеседнице тепло и по-доброму (милая, дорогая).\n"
    )

    rules = (
        "\n\nПРАВИЛА ОФОРМЛЕНИЯ И ТОНА:\n"
        "1. Пиши живо, заботливо и душевно, как лучшая подруга за чашкой кофе. Активно используй тёплые эмодзи в каждом абзаце (🌸, ☕️, ✨, 💛, 🌿, 🤗, 🍰, 🥑).\n"
        "2. СТРОГО разделяй абзацы пустой строкой. Никаких сплошных простыней текста: 1 мысль = 1 короткий абзац в 2-3 строчки.\n"
        "3. Важные акценты и названия выделяй двойными звёздочками: **вот так**.\n"
        "4. В блоке эмоциональной поддержки избегай сухости. Сначала искренне обними словами, дай выдохнуть, а затем мягко предложи 1-2 простых действия для заботы о себе.\n"
        "5. ОБЯЗАТЕЛЬНО раздели ответ ровно на две части меткой ===SPLIT=== на отдельной строке:\n"
        "   - Первая часть (до метки): тёплый краткий отклик и ключевая мысль (2-3 коротких абзаца).\n"
        "   ===SPLIT===\n"
        "   - Вторая часть (после метки): подробный пошаговый план, рецепт или конкретные советы.\n"
        f"{user_greeting}"
    )

    return f"{SYSTEM_PROMPT}\n{rules}"

def generate_reply(
    contents: list[types.Content],
    user_name: str | None = None,
) -> str:
    last_error = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=personalized_system_prompt(user_name),
                ),
            )
            return (response.text or "").strip()
        except Exception as error:
            last_error = error
            logger.warning("Gemini attempt %s failed: %s", attempt + 1, error)
            if attempt < 2:
                time.sleep(2)
    if last_error:
        raise last_error
    return ""


async def download_voice_audio(file_id: str) -> bytes:
    audio_stream = await bot.download(file_id)
    if audio_stream is None:
        raise RuntimeError("Telegram did not return the voice file")

    try:
        audio_bytes = audio_stream.read()
    finally:
        audio_stream.close()

    if not audio_bytes:
        raise ValueError("The voice message was empty")
    return audio_bytes


def get_user_request_lock(user_id: int) -> asyncio.Lock:
    lock = user_request_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        user_request_locks[user_id] = lock
    return lock


async def send_thinking_message(message: Message) -> Message:
    temporary_message = await message.answer(random.choice(THINKING_MESSAGES))
    try:
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    except Exception:
        logger.warning("Could not send typing action", exc_info=True)
    return temporary_message


async def delete_thinking_message(
    message: Message | int,
    temporary_message: Message | None,
) -> None:
    if not temporary_message:
        return
    try:
        chat_id = message.chat.id if hasattr(message, "chat") else message
        msg_id = temporary_message.message_id if hasattr(temporary_message, "message_id") else temporary_message
        await bot.delete_message(
            chat_id=chat_id,
            message_id=msg_id,
        )
    except Exception as err:
        logger.warning("Could not delete thinking message: %s", err)


def text_user_content(prompt: str) -> types.Content:
    return types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt)],
    )


def voice_user_content(audio_bytes: bytes) -> types.Content:
    return types.Content(
        role="user",
        parts=[
            types.Part.from_bytes(
                data=audio_bytes,
                mime_type="audio/ogg",
            ),
            types.Part.from_text(text=VOICE_REPLY_INSTRUCTION),
        ],
    )


async def send_final_response(message: Message, reply: str) -> None:
    parts = [p.strip() for p in reply.split("===SPLIT===") if p.strip()]

    # Если метки нет или ответ всего один — шлём как обычно
    if len(parts) <= 1:
        for idx, chunk in enumerate(split_response(reply)):
            is_last = (idx == len(split_response(reply)) - 1)
            await message.answer(
                format_telegram_html(chunk),
                reply_markup=MENU_KEYBOARD if is_last else None,
                parse_mode=ParseMode.HTML,
            )
        return

    # Если есть 2 части: короткое начало и подробности
    intro_text = parts[0]
    details_text = parts[1]

    # Создаём саму инлайн-кнопку
    expand_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📖 Развернуть подробнее", callback_data="expand_details")]
        ]
    )

    # Запоминаем подробности для этого пользователя
    pending_details[message.chat.id] = details_text

    # Отправляем только вводную часть с кнопкой
    await message.answer(
        format_telegram_html(intro_text),
        reply_markup=expand_keyboard,
        parse_mode=ParseMode.HTML,
    )

@dispatcher.callback_query(lambda c: c.data == "expand_details")
async def process_expand_details(callback: CallbackQuery) -> None:
    chat_id = callback.message.chat.id
    details = pending_details.pop(chat_id, None)

    # Убираем часики ожидания на кнопке
    await callback.answer()

    # Если вдруг нажали спустя полдня или память перезапустилась
    if not details:
        await callback.message.answer("Подробности уже открыты или устарели ☕️")
        return

    # Стираем кнопку под первым сообщением, чтобы не кликали дважды
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # Отправляем подробную часть и возвращаем нижнее меню с кнопками
    chunks = split_response(details)
    for idx, chunk in enumerate(chunks):
        is_last = (idx == len(chunks) - 1)
        await callback.message.answer(
            format_telegram_html(chunk),
            reply_markup=MENU_KEYBOARD if is_last else None,
            parse_mode=ParseMode.HTML,
     )

async def answer_with_gemini(
    message: Message,
    prompt: str | None = None,
    voice_file_id: str | None = None,
) -> None:
    user_id = message.from_user.id if message.from_user else message.chat.id
    if prompt is None and voice_file_id is None:
        return

    async with get_user_request_lock(user_id):
        temporary_message = await send_thinking_message(message)
        try:
            if voice_file_id is not None:
                audio_bytes = await download_voice_audio(voice_file_id)
                user_content = voice_user_content(audio_bytes)
            else:
                user_content = text_user_content(prompt or "")

            history = conversation_history_by_user.get(user_id, [])
            request_contents = [*history, user_content]
            reply = None

            for attempt in range(2):
                try:
                    reply = await asyncio.to_thread(
                        generate_reply,
                        request_contents,
                        user_names.get(user_id),
                    )
                    if reply:
                        break
                except Exception as error:
                    logger.warning("Attempt %s failed: %s", attempt + 1, error)
                    if attempt == 0:
                        await asyncio.sleep(2)
                    else:
                        error_message = (
                            "Немножко подвисла связь у серверов 🙈\n\n"
                            "Сделай пока глоток вкусного чая или кофе ☕️🍪\n"
                            "Загляни через 15–20 минут — всё как раз наладится, "
                            "и я буду на связи! 🌸✨"
                        )
                        await message.answer(
                            error_message,
                            reply_markup=MENU_KEYBOARD,
                        )
                        return

            if not reply:
                await message.answer(
                    "Ой, милая, отвлеклась на секунду! Нажми ещё раз на кнопочку меню 🌸",
                    reply_markup=MENU_KEYBOARD,
                )
                return

            append_history(user_id, user_content, reply)
            await send_final_response(message, reply)
        except Exception as general_error:
            logger.exception(
                "General error in answer_with_gemini: %s",
                general_error,
            )
            await message.answer(
                "Ой, милая, у меня на секунду закружилась голова от забот! 🙈 "
                "Сделай глоток чая — нажми ещё разок, я уже на связи ☕️✨",
                reply_markup=MENU_KEYBOARD,
            )
        finally:
            await delete_thinking_message(message, temporary_message)


@dispatcher.message(F.voice)
async def handle_voice_message(message: Message) -> None:
    if message.voice is None:
        return

    await answer_with_gemini(message, voice_file_id=message.voice.file_id)


@dispatcher.message(Command("food"))
async def handle_food_command(message: Message) -> None:
    await answer_with_gemini(message, MENU_BUTTONS[0])


@dispatcher.message(Command("chaos"))
async def handle_chaos_command(message: Message) -> None:
    await answer_with_gemini(message, MENU_BUTTONS[1])


@dispatcher.message(Command("plan"))
async def handle_plan_command(message: Message) -> None:
    await answer_with_gemini(message, MENU_BUTTONS[2])


@dispatcher.message(Command("support"))
async def handle_support_command(message: Message) -> None:
    await answer_with_gemini(message, MENU_BUTTONS[3])


@dispatcher.message(Command("reset_me"))
async def handle_reset_me(message: Message) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя; данные не изменены.")
        return

    user_id = message.from_user.id
    try:
        async with get_user_request_lock(user_id):
            await asyncio.to_thread(delete_user_data_from_database, user_id)
            user_names.pop(user_id, None)
            conversation_history_by_user.pop(user_id, None)
    except Exception as error:
        logger.exception("Failed to reset user data: %s", error)
        await message.answer("Не удалось очистить данные. Попробуй позже.")
        return

    await message.answer(
        "Готово — сохранённое имя и история диалога удалены. "
        "Отправь /start, чтобы проверить запуск как для нового пользователя.",
        reply_markup=MENU_KEYBOARD,
    )


@dispatcher.message(F.text)
async def handle_text(message: Message) -> None:
    prompt = (message.text or "").strip()
    if not prompt:
        return

    if message.from_user is None:
        return

    user_id = message.from_user.id

    # Если имя ещё не сохранено в памяти, берем его из профиля Telegram:
    if user_id not in user_names:
        clean_name = message.from_user.first_name or "дорогая"
        user_names[user_id] = clean_name
        try:
            with sqlite3.connect(STATE_DB_PATH) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO user_names (user_id, name) VALUES (?, ?)",
                    (user_id, clean_name),
                )
        except Exception as err:
            logger.warning("Could not save user name: %s", err)

    await answer_with_gemini(message, prompt)

async def main() -> None:
    logger.info("Starting Telegram bot with model %s", GEMINI_MODEL)
    initialize_user_state()
    try:
        # 1. Сначала мгновенно поднимаем веб-сервер для Render
        app = web.Application()
        async def health_check(request):
            return web.Response(text="OK")
        app.router.add_get("/", health_check)
        app.router.add_get("/health", health_check)

        runner = web.AppRunner(app)
        await runner.setup()
        port = int(os.getenv("PORT", "10000"))
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info(f"Web server started on port {port}")

        # 2. Настраиваем команды и запускаем бота
        try:
            await bot.set_my_commands(BOT_COMMANDS)
            await bot.set_chat_menu_button()
        except Exception as e:
            logger.warning(f"Failed to set bot commands: {e}")

        logger.info("Starting polling...")
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
        client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
