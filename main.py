import asyncio
import html
import io
import logging
import os
from aiohttp import web
import time

import random
import re
import sqlite3

import psycopg

from aiogram import BaseMiddleware, Bot, Dispatcher, F
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
START_OFFSET = 12  # Наши первые гости, пришедшие до постоянного счётчика
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
BANNER_PHOTO_ID = "AgACAgIAAxkBAAIIL2rQhiE0ysuGPvBGRKM2DGmuKm8SAALSGGsbTc2JSv_n8D26j6uhAQADAgADeQADPQQ"

# Горизонтальные баннеры Telegram. Позже сюда можно добавить несколько file_id на рубрику.
BANNER_START = [BANNER_PHOTO_ID]  # стартовое приветствие
FOOD_BANNERS = [
    "AgACAgIAAxkBAAIHdGrOdXYmWYA7axciENDwEAgzwHatAALrJGsbG09wSqMQS_xQEO2lAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIHcmrOdXYOASVucKJ4EwUXQvKF9SvMAALpJGsbG09wSrXITkQkQV3YAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIHeGrOdXapiT2h8yNNXiOmloCeXgq-AALvJGsbG09wStLAph9PNSQxAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIHd2rOdXYdbSWunpYWDnfKCrJR0yAbAALuJGsbG09wShVu-yF1EgjRAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIHdmrOdXbtBXs8suWjDKFRzN0NI5MlAALtJGsbG09wSt7IR0mnVK5pAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIHc2rOdXbt1yVP9fSB6iVNoHKs0FVhAALqJGsbG09wSscrzLJA-4q2AQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIHdWrOdXaeJJ9eWDO98vhZ2GLjbX_8AALsJGsbG09wShnBgyJS80GIAQADAgADdwADPQQ",
    "AgACAgIAAyEFAAMBA3oyOgADFmrPPhQlyqihU5xnURZuKhd1Yho8AALnJGsbG09wSuFIwgjfjMglAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIHcWrOdXYmtZSmH39Ry6fRRgE2l0LNAALoJGsbG09wSrWpcVRebzTYAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIHeWrOdXa5ClMWHVD_LwRaLGoMljUOAALwJGsbG09wSnYh7UBPJXpqAQADAgADdwADPQQ",
]
food_banner_index = 0
clean_banner_index = 0
plan_banner_index = 0
BANNER_FOOD = FOOD_BANNERS  # накормить семью
BANNER_CLEAN = [
    "AgACAgIAAxkBAAIIIWrQgWw6fOaSSXAOByRN0S2mBFTwAAK6GGsbTc2JSrXbPtBeRa9eAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIIH2rQgWyshf5g_tnocRBQaO-C28-SAAK4GGsbTc2JSsJbBA_O4rCDAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIIIG2rQgWxlt1vm7yBUWm3Lq4ItxCNvAAK0GGsbTc2JSsLujMjveYYFAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIIHmrQgWwkfyA9lbT0QJkLcsKBdUQjAAK3GGsbTc2JSkPjJyo7LV2FAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIIImrQgWwWvlrKJ7rYNcl2O9circOlAAK7GGsbTc2JSnXo-3GGK9syAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIIIGrQgWww3VyZRo-9h_i855r3Fm2tAAK5GGsbTc2JSttX3GSqKuE8AQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIIJGrQgWwLA1SX-h0qQEXT4JaYmqiLAAK9GGsbTc2JSk8Kw79xHxxuAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIII2rQgWyz_gfcI3XCb0j3KMJ2OkVdAAK8GGsbTc2JSjciMU3C5KIvAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIIHWrQgWwTlyWgvONDLaj5OfM5NmwwAAK2GGsbTc2JSl2Zb_ziQjBMAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIIHGrQgWxTFyWZAAH_DJ64hucQOu8VeAACtRhrG03NiUrP6kQDB93TggEAAwIAA3cAAz0E",
]  # разгрести хаос
BANNER_PLAN = [
    "AgACAgIAAxkBAAIJEGrSZZCUWgnghVOOJsbU8BmdzRiAAALlImsbRneRSoTPGC6XyjEgAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIJE2rSZZA_LXaJOtvvoNWsIjUs41j6AALoImsbRneRSq54nMsNA999AQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIJD2rSZZDoAAFZ4NavtYECdfrMixjsqQAC5CJrG0Z3kUpKUElkTYl6VQEAAwIAA3cAAz0E",
    "AgACAgIAAxkBAAIJEWrSZZDbapvAQch-UkBQlUWNO-VXAALmImsbRneRSgU7k7AoFAjRAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIJEmrSZZDKtahHzBd7-r_PH2I2ujsFAALnImsbRneRStkPGjz9djutAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIJFGrSZZAB6CS5wU6n-FKjB4Du9ggJAALpImsbRneRSuwWPIT0M-huAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIJFmrSZZBrIeE8wGgQQLfRXCZT1fQRAALrImsbRneRSmYDw3X1KkBBAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIJF2rSZZBDzIt1wgNkuoYFEl6c3nmnAALsImsbRneRStZZS3HJUUa0AQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIJFWrSZZBZxNZ-gsebhHshUTAkI5x1AALqImsbRneRSjschJyiPhCRAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIJGGrSZZApaF4gXDwliwABNOLCnUzcdAAC7SJrG0Z3kUruiQl3bdqUcwEAAwIAA3cAAz0E",
]  # день по полочкам, ротация сохраняется в SQLite
BANNER_SUPPORT = [
    "AgACAgIAAxkBAAIJw2rVzEEgoFDE54b5SGRG4eL9vBkYAAISIGsbVU2wSjFyEdoeYfr2AQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIJvmrVzEGbr2qPIwnAZS0o2gdw7-A3AAINIGsbVU2wSubjF4MnfpxjAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIJvGrVzEGSPXlWZ_4g2arl4DEkFgEtAAILIGsbVU2wSsl2KaiEOEADAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIJxGrVzEFTEqpgf3X8cUDB3S3IlFpUAAITIGsbVU2wSmy7V3mT-V4tAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIJu2rVzEEeFCEucqouzgWUSeMCKRCmAAIKIGsbVU2wSv3-_8MFHoHbAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIJvWrVzEGqGC9Aw8BwGDjqGxMTleE9AAIMIGsbVU2wSincn0xXOI71AQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIJwWrVzEFb016y3Ztwi1i8uii3yecZAAIQIGsbVU2wSuzIPAABysB7BwEAAwIAA3cAAz0E",
    "AgACAgIAAxkBAAIJwGrVzEGyAdndvUh9zsYiWf7iPHgGAAIPIGsbVU2wSsqE_kQLASgLAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIJwmrVzEF5rlsVZrT_ek2UpXxC7LbZAAIRIGsbVU2wSh_gtvroJ_IOAQADAgADdwADPQQ",
    "AgACAgIAAxkBAAIJv2rVzEHKL4Qj3oKlS6wZcoZzJNmwAAIOIGsbVU2wSiGG0Jm-Z0hrAQADAgADdwADPQQ",
]  # тёплая поддержка
support_banner_index = 0

SUPPORT_SCENARIOS = {
    "vent": {
        "label": "💬 Выговориться",
        "greeting": (
            "Я рядом 🤍 Здесь можно всё: злиться, жаловаться, ругаться или просто вывалить весь ком мыслей. "
            "Не подбирай слова, я не буду тебя судить или читать нотации. Выгружай всё, что накипело! ☕️"
        ),
        "instruction": (
            "Роль: близкая понимающая подруга за чашкой чая ☕️.\n"
            "Формула ответа:\n"
            "1. Живая реакция на её слова: раздели эмоции, признай, как это бесит/выматывает (без заумных терминов вроде 'звенящая пустота' или 'ресурс').\n"
            "2. Легализуй забить на дела: скажи прямо, что сейчас можно забить на идеальный порядок, готовку и режим.\n"
            "3. Одно ультра-простое микродействие на 1 минуту, чтобы переключить тело (умыться холодной водой, открыть окно и сделать вдох, выпить залпом стакан воды, лечь на пол на 2 минуты).\n"
            "Пиши живо, с эмодзи, не задавай навязчивых вопросов в конце и не устраивай допрос."
        ),
    },
    "warm": {
        "label": "🤍 Тёплые слова",
        "greeting": (
            "Положи руку на грудь и сделай глубокий вдох-выдох 🌸\n\n"
            "Ты не плохая мама, ты просто живой человек, который дико устал. "
            "Ты тащишь на себе невидимый вагон дел, и то, что силы кончились — это нормально.\n\n"
            "Напиши пару слов, от чего сегодня тяжелее всего, а я побуду твоей опорой и обниму тебя словами 🫂✨"
        ),
        "instruction": (
            "Роль: любящая, тёплая опора 🫂.\n"
            "Формула ответа:\n"
            "1. Теплое словесное объятие: сними вину, напомни, что один дурацкий день не делает её плохой мамой.\n"
            "2. Разрешение выдохнуть: 'Остановись, ты уже сделала достаточно на сегодня'.\n"
            "3. Конкретная маленькая забота о себе прямо сейчас (заварить чай в любимую кружку, съесть вкусняшку в тишине, завернуться в плед).\n"
            "Используй уютные эмодзи (🤍, 🌸, ☕️, 🫂). Никаких нравоучений и длинных лекций."
        ),
    },
    "advice": {
        "label": "🌿 Совет",
        "greeting": (
            "Когда в голове каша, сложно понять, за что хвататься 🤯\n\n"
            "Черкни в двух словах, в чём затык? Разложим всё на раз-два и выберем самое простое решение на сегодня, без подвигов 🌿"
        ),
        "instruction": (
            "Роль: практичная, сообразительная подруга 💡.\n"
            "Формула ответа:\n"
            "1. Если мама жалуется на упадок сил и аврал — срежь углы и разреши отложить неприоритетные дела.\n"
            "2. Если мама спрашивает, КАК СОБРАТЬСЯ или С ЧЕГО НАЧАТЬ конкретное дело — НЕ отговаривай её и не говори «забей»! Помоги преодолеть ступор:\n"
            "   - Сними страх масштаба (например, «делаем только 1 окно, а не всю квартиру»).\n"
            "   - Разбей задачу на 2–3 элементарных микрошага по 5 минут.\n"
            "   - Дай быстрый практичный лайфхак, чтобы облегчить процесс.\n"
            "Пиши бодро, с поддержкой и эмодзи (💡, 🌿, ✨), без нудных лекций."
        ),
    },
    "pause": {
        "label": "☕ Передохнуть",
        "greeting": (
            "Стоп-машина! 🛑 Прямо сейчас поставь мир на паузу.\n\n"
            "Посуда не убежит, стирка подождёт, мир не рухнет. "
            "Опусти плечи, разожми челюсть и просто присядь на 5 минут. Помолчим вместе или включить режим тишины? ☕️🌿"
        ),
        "instruction": (
            "Роль: хранитель тишины и замедления ☕️.\n"
            "Формула ответа:\n"
            "1. Призыв к телесному расслаблению: напомни опустить плечи, расслабить лицо и глубоко выдохнуть.\n"
            "2. Короткая уютная зарисовка или предложение просто залипнуть в окно/попить чай в тишине.\n"
            "Не давай дыхательных упражнений по счёту или сложных заданий. Мягко, атмосферно, с эмодзи 🌿✨"
        ),
    },
    "wins": {
        "label": "🌷 Маленькие победы",
        "greeting": (
            "В мамском дне сурка кажется, будто мы пашем с утра до ночи, а результата ноль 🙈 Но это обман зрения!\n\n"
            "Если дети сыты, дома никто не пострадал и ты ещё на ногах — ты уже герой дня. "
            "Что сегодня всё-таки получилось сделать, пусть даже самую мелочь? Давай найдём твои победы! 🌷✨"
        ),
        "instruction": (
            "Роль: подруга, которая искренне гордится и замечает невидимый труд 🌷.\n"
            "Формула ответа:\n"
            "1. Восхитись даже мелочью: 'Ты выдержала этот ор? Да тебе памятник надо!' или 'Суп сварила — это подвиг!'.\n"
            "2. Верни ей веру в себя: покажи, что это огромный труд, который она привыкла обесценивать.\n"
            "3. Предложи наградить себя прямо сейчас (кусочек шоколадки, 10 минут сериала, полежать ногами кверху).\n"
            "Ярко, ободряюще, с тёплыми эмодзи 🎉✨"
        ),
    },
}
support_sessions: dict[int, str] = {}
# Ephemeral states only; no photo or message content is stored in analytics.
radiance_states: dict[int, str] = {}
pending_kids_age: set[int] = set()
SUPPORT_STYLE = (
    "Общайся тепло, естественно и конкретно — как внимательная подруга, а не по психологическому скрипту. "
    "Отвечай на то, что мама действительно сказала, простым разговорным языком. Не приписывай ей чувства, "
    "страхи, мотивы, обстоятельства или достижения, которых нет в её сообщениях и истории. Не превращай "
    "короткую реплику в общий монолог о материнстве, усталости или одиночестве. Не пересказывай сообщение "
    "длинно и не используй канцелярские или абстрактные обороты, если можно сказать проще. Обычно достаточно "
    "одного содержательного абзаца, иногда двух; длина зависит от смысла, не от жёсткого лимита. Не добавляй "
    "несколько сообщений с повторяющимися рассуждениями, если можно ответить цельно. Не заканчивай каждую "
    "реплику вопросом и не превращай диалог в допрос. Не предлагай выговориться автоматически и не задавай "
    "вопросы ради продолжения разговора: следуй конкретному выбранному сценарию поддержки. Если сценарий "
    "предполагает совет, предложи один-два конкретных реалистичных шага с учётом обстоятельств. Не навязывай "
    "отдых, дыхательные практики или делегирование, если это не соответствует выбранному сценарию. Не хвали "
    "автоматически и не придумывай достижения. Избегай повторяющихся шаблонов вроде «я внимательно тебя слушаю», "
    "«я рядом», «ты имеешь право отдыхать», «давай выдохнем»; не добавляй обязательные сердечки или цветы. "
    "Учитывай историю разговора, не повторяй стартовый ответ после каждой реплики. Сценарий меняется только "
    "после явного выбора пользователя; при смене сценария сохраняй полезный контекст, но отвечай согласно "
    "новому запросу. Не объявляй «сценарий принят», если это не нужно для понимания интерфейса. Не рекламируй "
    "Greenway, товары, услуги или ссылки. Не ставь диагнозы и не обещай гарантированный результат. При "
    "непосредственной опасности для себя или другого человека бережно посоветуй немедленно обратиться в местную "
    "экстренную службу и к надёжному человеку рядом, не оставаться в одиночестве и по возможности отойти от "
    "средств причинения вреда."
)
def support_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=item["label"], callback_data=f"support:choose:{key}")]
            for key, item in SUPPORT_SCENARIOS.items()
        ] + [[InlineKeyboardButton(text="🏠 В главное меню", callback_data="support:home")]]
    )


def support_return_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💛 Выбрать другой вариант", callback_data="support:choose_again")],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="support:home")],
        ]
    )


async def start_support_flow(message: Message, request_user_id: int | None = None) -> None:
    global support_banner_index
    user_id = request_user_id or (message.from_user.id if message.from_user else message.chat.id)
    # Повторный вход показывает выбор, но не сбрасывает активный сценарий.
    # Смена сценария и очистка его истории происходят атомарно при выборе кнопки.
    banner_ids = (
        BANNER_SUPPORT[support_banner_index:] + BANNER_SUPPORT[:support_banner_index]
    ) if BANNER_SUPPORT else []
    if BANNER_SUPPORT:
        support_banner_index = (support_banner_index + 1) % len(BANNER_SUPPORT)

    caption = (
        "🫂 <b>Тёплая поддержка</b>\n\n"
        "Какой поддержки тебе хочется сейчас? 💛"
    )
    # Сначала отправляем одно вводное сообщение: фото, текст и кнопки вместе.
    for photo_id in banner_ids:
        try:
            await message.answer_photo(
                photo=photo_id,
                caption=caption,
                reply_markup=support_choice_keyboard(),
                parse_mode=ParseMode.HTML,
            )
            return
        except Exception as error:
            logger.warning("Could not send support banner photo: %s", error)

    # Если Telegram не принимает ни одну картинку, кнопки всё равно доступны.
    await message.answer(
        caption,
        reply_markup=support_choice_keyboard(),
        parse_mode=ParseMode.HTML,
    )


START_CAPTION = (
    "🌸 <b>Привет, дорогая! Я твой бот «Мама 24/7».</b>\n\n"
    "Твоя личная цифровая подруга, когда силы на исходе, в голове миллион задач, "
    "а дома лёгкий хаос.\n\n"
    "Я здесь, чтобы беречь твой ресурс и разгружать голову:\n"
    "🍳 <b>Накормить семью</b> — придумаю быстрый ужин за 20 минут из того, что есть в холодильнике\n"
    "🧹 <b>Разгрести хаос</b> — подскажу, как навести порядок за 15 минут без едкой химии\n"
    "📋 <b>День по полочкам</b> — разложу дела без спешки и чувства вины\n"
    "🫂 <b>Тёплая поддержка</b> — поддержу и напомню выпить горячий чай ☕️\n"
    "✨ <b>Моё сияние</b> — ориентировочная палитра цветов и идеи ухода\n"
    "🧸 <b>Занять ребёнка</b> — безопасная игра на несколько минут\n\n"
    "<b>С чего начнём сегодня? Выбирай кнопку внизу 👇</b>"
)
MENU_BUTTONS = (
    "🍲 Накормить семью",
    "🧹 Разгрести хаос",
    "📅 День по полочкам",
    "🫂 Тёплая поддержка",
    "✨ Моё сияние",
    "🧸 Занять ребёнка",
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
- «🍲 Накормить семью»: предлагай простые, сытные и аппетитные семейные блюда из обычных недорогих продуктов, которые легко найти в ближайшем магазине или часто уже есть дома. Главный приоритет — минимум активного времени у плиты: обычно 15–30 минут, без сложных техник, редких ингредиентов и горы посуды. Если блюдо требует долгого запекания или варки, честно укажи общее время и по возможности предложи более быстрый вариант. Не начинай ответы с выдуманных сезонных вступлений вроде «лето, солнышко, жара»; упоминай сезон только если это действительно уместно и соответствует текущей дате.
- РАЗНООБРАЗИЕ: учитывай предыдущие блюда в истории диалога и не предлагай снова то же блюдо или почти такой же рецепт. Чередуй основы и способы приготовления: курица, фарш, яйца, творог, овощи, крупы, макароны, супы, запеканки, блюда на сковороде, салаты и простые блюда без мяса. Не делай каждый рецепт пастой, оладьями или курицей; меняй вкус, основные продукты и формат блюда. Не выдумывай, какие продукты есть у пользователя.
- Только в ответах рубрики «🍲 Накормить семью» в самом конце задай один короткий дружелюбный вопрос о продуктах, которые уже есть дома. Например: «Хочешь, подберём блюдо из того, что уже есть? Напиши, какие продукты у тебя сейчас в холодильнике 😊». В остальных рубриках НЕ задавай вопрос про продукты и НЕ добавляй предложение подобрать блюдо; заканчивай ответ по теме выбранной рубрики.
- «🧹 Разгрести хаос»: экспресс-уборка за 5–15 минут БЕЗ едкой химии и БЕЗ дедовских методов (никакой соды, уксуса и горчичного порошка!). Рекомендуй эстетичный эко-подход в стиле Greenway: салфетки и файберы из микроволокна (работают от одной воды, убирают жир и грязь без капли химии), натуральную очищающую пасту или кислородный эко-очиститель для сложных пятен.
- «📅 День по полочкам»: план ориентирован на маму и сочетает заботу о детях, домашние дела и отдых, но не выдумывает обстоятельства семьи. Учитывай известный контекст: если известно, что у мамы младенец или малыш, предусматривай гибкие окна для кормлений, прогулки и возможного дневного сна, помня, что планы могут часто меняться и ребёнок не обязан долго занимать себя самостоятельно. Если дети старше и известны школа, детский сад или занятия, учитывай их. Если возраст и режим неизвестны, предложи гибкий план для мамы с блоками заботы о детях, бытовых дел и отдыха — без выдуманных расписаний, возрастов и обязательств. Если для полезного плана действительно не хватает важной информации, задай один короткий вопрос; не превращай ответ в анкету. Временные блоки — ориентир: предлагай переносить дела, сокращать список и менять порядок по потребностям детей и состоянию мамы. Пиши короткими абзацами, тепло, на «ты», с лёгким юмором и без чувства вины. Не обещай, что всё обязательно будет выполнено, и не превращай правила продуктивности в обязательные нормы. Не вставляй рекламу автоматически. Greenway упоминай только если пользователь сам спрашивает или рекомендация действительно уместна; объясняй конкретно и естественно, без расплывчатых фраз вроде «полезный напиток вот отсюда» и без необоснованных обещаний пользы для здоровья. Если даёшь ссылку, используй действующую реферальную ссылку из правил ниже.
- «🫂 Тёплая поддержка»: следуй выбранному сценарию из SUPPORT_SCENARIOS. Будь естественной, не используй постоянные обращения «милая», «дорогая», не выдумывай чувства или обстоятельства, не давай непрошеных советов и не рекламируй товары. При непосредственной опасности направь к местной экстренной помощи и надёжному человеку рядом.

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
        [KeyboardButton(text=MENU_BUTTONS[4]), KeyboardButton(text=MENU_BUTTONS[5])],
    ],
    resize_keyboard=True,
    is_persistent=False,
    input_field_placeholder="Выбери, чем помочь",
)

inline_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🍳 Накормить семью", callback_data="menu_food")],
        [InlineKeyboardButton(text="🧹 Разгрести хаос", callback_data="menu_clean")],
        [InlineKeyboardButton(text="📋 День по полочкам", callback_data="menu_plan")],
        [InlineKeyboardButton(text="🫂 Тёплая поддержка", callback_data="menu_support")],
        [InlineKeyboardButton(text="✨ Моё сияние", callback_data="menu_radiance")],
        [InlineKeyboardButton(text="🧸 Занять ребёнка", callback_data="menu_kids")],
    ]
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
    http_options={
        "base_url": "https://api.proxyapi.ru/google",
        # Ограничиваем один запрос к Gemini 30 секундами, чтобы бот не зависал.
        "timeout": 30000,
    },
)
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dispatcher = Dispatcher()

class AnalyticsCallbackMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user is not None:
            schedule_user_registration(user)
            callback_data = getattr(event, "data", None)
            if callback_data:
                section, button_id = analytics_button_info(callback_data)
                schedule_analytics_event(user.id, "button_click", section, button_id)
        return await handler(event, data)

class AnalyticsMessageMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user is not None:
            schedule_user_registration(user)
            text_value = getattr(event, "text", None)
            button_ids = {
                MENU_BUTTONS[0]: ("food", "menu_food"),
                MENU_BUTTONS[1]: ("clean", "menu_clean"),
                MENU_BUTTONS[2]: ("plan", "menu_plan"),
                MENU_BUTTONS[3]: ("support", "menu_support"),
                MENU_BUTTONS[4]: ("radiance", "menu_radiance"),
                MENU_BUTTONS[5]: ("kids", "menu_kids"),
            }
            if text_value in button_ids:
                section, button_id = button_ids[text_value]
                schedule_analytics_event(user.id, "button_click", section, button_id)
        return await handler(event, data)

dispatcher.callback_query.outer_middleware(AnalyticsCallbackMiddleware())
dispatcher.message.outer_middleware(AnalyticsMessageMiddleware())

user_names: dict[int, str] = {}
pending_details: dict[int, str] = {}
pending_details_food: set[int] = set()
conversation_history_by_user: dict[int, list[types.Content]] = {}
user_request_locks: dict[int, asyncio.Lock] = {}
chaos_sessions: dict[int, dict] = {}
chaos_session_counter = 0
pending_family_profile: dict[int, dict] = {}

CHAOS_ZONES = {
    "kitchen": "кухня",
    "kids": "игрушки и детская",
    "clothes": "одежда и вещи",
    "living": "гостиная",
    "everywhere": "понемногу везде",
}
CHAOS_ENERGIES = {
    "low": "низкий",
    "normal": "обычный",
    "high": "высокий",
}
CHAOS_DURATIONS = (5, 10, 15)

# Короткие конечные маршруты: прогрессом управляет код, а не свободная генерация Gemini.
# Concrete task pools; session state and timer are managed by Python.
CHAOS_STEP_SEQUENCES = {
    "kitchen": [
        "Унеси кружки и тарелки в раковину.",
        "Убери продукты и упаковки со стола на места.",
        "Выброси видимый мусор и пустые упаковки.",
        "Собери крошки со стола влажной салфеткой.",
        "Протри кухонный стол.",
        "Убери чистую посуду, если она высохла.",
        "Освободи один небольшой участок столешницы.",
        "Протри раковину и смеситель.",
        "Верни специи и продукты, которые стоят не на месте, в шкаф.",
        "Протри ручки двух-трёх кухонных шкафчиков.",
    ],
    "kids": [
        "Собери крупные игрушки в одну корзину.",
        "Сложи кубики или конструктор в коробку.",
        "Положи детские книги на одну полку.",
        "Собери карандаши и фломастеры в пенал или стакан.",
        "Убери одежду с пола в корзину для стирки.",
        "Сложи плед или покрывало на кровати.",
        "Собери мелкие игрушки в коробку, не сортируя.",
        "Освободи небольшой участок пола.",
        "Убери со стола для занятий то, что уже не нужно.",
        "Поставь обувь у двери парами.",
    ],
    "clothes": [
        "Собери грязную одежду в корзину для стирки.",
        "Повесь на место две чистые вещи.",
        "Сложи две-три вещи, которые уже можно убрать.",
        "Поставь обувь парами у стены или в обувницу.",
        "Собери носки в пары, одиночные отложи отдельно.",
        "Убери сумки и рюкзаки на обычные места.",
        "Освободи один стул от одежды: чистое повесь, грязное — в корзину.",
        "Сложи домашнюю одежду в одну стопку.",
        "Убери аксессуары в коробку или ящик.",
        "Освободи небольшой участок пола от одежды и обуви.",
    ],
    "living": [
        "Отнеси чашки и тарелки из гостиной на кухню.",
        "Убери с дивана вещи, которые там не должны лежать.",
        "Сложи плед и расправь подушки на диване.",
        "Собери пульты и мелочи в одно постоянное место.",
        "Убери журналы и книги на полку или в стопку.",
        "Протри журнальный столик влажной салфеткой.",
        "Собери видимый мусор и выброси его.",
        "Убери вещи с кресла или стула.",
        "Освободи одну небольшую поверхность от лишнего.",
        "Отнеси на место три вещи, оставшиеся в гостиной.",
    ],
    "everywhere": [
        "Отнеси кружки и тарелки, которые стоят не на кухне, на кухню.",
        "Собери видимый мусор и выброси его.",
        "Подними с пола три вещи и положи на привычные места.",
        "Собери разбросанные мелочи в корзинку, не сортируя.",
        "Освободи один стол от лишних вещей.",
        "Сложи плед и расправь подушки на диване или кровати.",
        "Собери грязную одежду в корзину для стирки.",
        "Поставь обувь у входа парами.",
        "Отнеси книги и игрушки туда, где они обычно хранятся.",
        "Протри влажной салфеткой одну освобождённую поверхность.",
    ],
}


def append_history(user_id: int, user_content: types.Content | None, model_text: str) -> None:
    history = conversation_history_by_user.setdefault(user_id, [])
    if user_content is not None:
        history.append(user_content)
    history.append(
        types.Content(
            role="model",
            parts=[types.Part.from_text(text=model_text)],
        )
    )
    if len(history) > 20:
        conversation_history_by_user[user_id] = history[-20:]


class FamilyProfileUnavailable(Exception):
    """Raised when persistent family-profile storage is not configured or reachable."""


AGE_PATTERN = re.compile(
    r"(?P<value>\d{1,3})\s*(?P<unit>месяц(?:а|ев)?|мес\.?|год(?:а|ов)?|лет)(?=\W|$)",
    re.IGNORECASE,
)


def parse_child_ages(text: str) -> list[dict] | None:
    """Parse one age per comma/newline-separated child, ordered oldest to youngest."""
    if not text or len(text) > 500:
        return None
    segments = [part.strip() for part in re.split(r"[,;\n]+", text) if part.strip()]
    if not segments:
        return None

    ages = []
    for segment in segments:
        matches = list(AGE_PATTERN.finditer(segment))
        if len(matches) != 1:
            return None
        match = matches[0]
        value = int(match.group("value"))
        unit_text = match.group("unit").lower()
        unit = "months" if unit_text.startswith(("месяц", "мес")) else "years"
        if (unit == "months" and value > 1440) or (unit == "years" and value > 120):
            return None
        ages.append({
            "child_number": len(ages) + 1,
            "age_value": value,
            "age_unit": unit,
        })
    return ages


def format_child_age(age: dict) -> str:
    value = int(age["age_value"])
    if age["age_unit"] == "months":
        remainder = value % 100
        last_digit = value % 10
        word = "месяц" if last_digit == 1 and remainder != 11 else (
            "месяца" if 2 <= last_digit <= 4 and not 12 <= remainder <= 14 else "месяцев"
        )
        return f"{value} {word}"
    remainder = value % 100
    last_digit = value % 10
    word = "год" if last_digit == 1 and remainder != 11 else (
        "года" if 2 <= last_digit <= 4 and not 12 <= remainder <= 14 else "лет"
    )
    return f"{value} {word}"


def family_age_summary(ages: list[dict]) -> str:
    labels = {
        1: "старший ребёнок",
        2: "второй ребёнок",
        3: "третий ребёнок",
    }
    lines = []
    for age in ages:
        child_number = int(age["child_number"])
        label = labels.get(child_number)
        if label is None:
            label = "ребёнок №" + str(child_number)
        age_text = format_child_age(age)
        line = "• " + label + ": " + age_text
        lines.append(line)
    return "\n".join(lines)


def load_family_ages(user_id: int) -> list[dict]:
    dsn = os.getenv("SUPABASE_DB_URL")
    if not dsn:
        raise FamilyProfileUnavailable("SUPABASE_DB_URL is not configured")
    try:
        with psycopg.connect(dsn, connect_timeout=4, sslmode="require") as connection:
            rows = connection.execute(
                """
                SELECT child_number, age_value, age_unit
                FROM public.children
                WHERE telegram_user_id = %s
                ORDER BY child_number
                """,
                (user_id,),
            ).fetchall()
        return [
            {"child_number": int(number), "age_value": int(value), "age_unit": unit}
            for number, value, unit in rows
        ]
    except Exception as error:
        logger.warning("Family profile read DB error: %s", type(error).__name__)
        raise FamilyProfileUnavailable(type(error).__name__) from None


def save_family_ages(user_id: int, ages: list[dict]) -> None:
    dsn = os.getenv("SUPABASE_DB_URL")
    if not dsn:
        raise FamilyProfileUnavailable("SUPABASE_DB_URL is not configured")
    try:
        with psycopg.connect(dsn, connect_timeout=4, sslmode="require") as connection:
            connection.execute(
                """
                INSERT INTO public.mom_profiles (telegram_user_id, updated_at)
                VALUES (%s, now())
                ON CONFLICT (telegram_user_id)
                DO UPDATE SET updated_at = now()
                """,
                (user_id,),
            )
            # This confirmation flow asks for the complete age list in birth order.
            # Replacing that list avoids duplicate rows when ages are corrected.
            connection.execute(
                "DELETE FROM public.children WHERE telegram_user_id = %s",
                (user_id,),
            )
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO public.children
                        (telegram_user_id, child_number, age_value, age_unit, updated_at)
                    VALUES (%s, %s, %s, %s, now())
                    """,
                    [
                        (user_id, age["child_number"], age["age_value"], age["age_unit"])
                        for age in ages
                    ],
                )
    except Exception as error:
        # Log only the exception class, never connection strings or credentials.
        logger.warning("Family profile save DB error: %s", type(error).__name__)
        raise FamilyProfileUnavailable(type(error).__name__) from None


def delete_family_profile(user_id: int) -> None:
    dsn = os.getenv("SUPABASE_DB_URL")
    # Before the connection is configured, this code has not saved remote profiles.
    if not dsn:
        return
    try:
        with psycopg.connect(dsn, connect_timeout=4, sslmode="require") as connection:
            connection.execute(
                "DELETE FROM public.mom_profiles WHERE telegram_user_id = %s",
                (user_id,),
            )
    except Exception as error:
        raise FamilyProfileUnavailable(type(error).__name__) from None


async def start_family_age_collection(
    message: Message,
    user_id: int,
    had_existing_profile: bool,
) -> None:
    pending_family_profile[user_id] = {
        "stage": "collecting",
        "had_existing_profile": had_existing_profile,
    }
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Без возраста", callback_data="family_age:skip")]
        ]
    )
    await message.answer(
        "Чтобы сделать план полезнее, напиши возраст каждого ребёнка по порядку "
        "от старшего к младшему — по одному возрасту через запятую. Например: "
        "14 лет, 7 лет, 8 месяцев. Можно указывать месяцы для малышей и годы для старших.\n\n"
        "Я сначала покажу, что собираюсь запомнить, и сохраню только после твоего подтверждения.",
        reply_markup=keyboard,
    )


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
        # Реестр уже приветствованных гостей не удаляется командой /reset_me.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS welcomed_users (
                user_id INTEGER PRIMARY KEY,
                first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Переносим уже известных пользователей в постоянный реестр без повторных уведомлений.
        connection.execute(
            """
            INSERT OR IGNORE INTO welcomed_users (user_id)
            SELECT user_id FROM user_names
            """
        )
        connection.commit()
        name_rows = connection.execute(
            "SELECT user_id, name FROM user_names"
        ).fetchall()
    user_names = {int(user_id): name for user_id, name in name_rows}


_analytics_last_registered: dict[int, float] = {}
ANALYTICS_REGISTRATION_COOLDOWN_SECONDS = 300
ANALYTICS_TASK_TIMEOUT_SECONDS = 4.0
_analytics_tasks: set[asyncio.Task] = set()

def _schedule_analytics_task(function, *args) -> None:
    task = asyncio.create_task(_run_analytics_task(function, *args))
    _analytics_tasks.add(task)
    task.add_done_callback(_analytics_tasks.discard)

def _analytics_connect():
    dsn = os.getenv("SUPABASE_DB_URL")
    if not dsn:
        raise RuntimeError("SUPABASE_DB_URL is not configured")
    connection = psycopg.connect(dsn, connect_timeout=2)
    connection.execute("SET statement_timeout = '2500ms'")
    return connection

def _register_user_sync(telegram_user_id: int, username: str | None, display_name: str | None) -> None:
    with _analytics_connect() as connection:
        connection.execute("""
            INSERT INTO public.bot_users
                (telegram_user_id, first_seen_at, last_seen_at, username, display_name)
            VALUES (%s, now(), now(), %s, %s)
            ON CONFLICT (telegram_user_id) DO UPDATE SET
                first_seen_at = LEAST(COALESCE(public.bot_users.first_seen_at, EXCLUDED.first_seen_at), EXCLUDED.first_seen_at),
                last_seen_at = GREATEST(public.bot_users.last_seen_at, EXCLUDED.last_seen_at),
                username = COALESCE(EXCLUDED.username, public.bot_users.username),
                display_name = COALESCE(NULLIF(EXCLUDED.display_name, ''), public.bot_users.display_name)
            """, (telegram_user_id, username, display_name))

def _backfill_sqlite_users_sync() -> None:
    with sqlite3.connect(STATE_DB_PATH) as local_connection:
        rows = local_connection.execute("""
            SELECT w.user_id, w.first_seen_at, COALESCE(u.name, '')
            FROM welcomed_users AS w
            LEFT JOIN user_names AS u ON u.user_id = w.user_id
        """).fetchall()
    if not rows:
        return
    with _analytics_connect() as connection:
        for user_id, first_seen_at, display_name in rows:
            connection.execute("""
                INSERT INTO public.bot_users
                    (telegram_user_id, first_seen_at, last_seen_at, display_name)
                VALUES (%s, %s::timestamptz, %s::timestamptz, %s)
                ON CONFLICT (telegram_user_id) DO UPDATE SET
                    first_seen_at = LEAST(COALESCE(public.bot_users.first_seen_at, EXCLUDED.first_seen_at), EXCLUDED.first_seen_at),
                    last_seen_at = GREATEST(public.bot_users.last_seen_at, EXCLUDED.last_seen_at),
                    display_name = COALESCE(NULLIF(EXCLUDED.display_name, ''), public.bot_users.display_name)
            """, (user_id, first_seen_at, first_seen_at, display_name))

async def _run_analytics_task(function, *args) -> None:
    try:
        await asyncio.wait_for(asyncio.to_thread(function, *args), timeout=ANALYTICS_TASK_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.warning("Analytics task %s failed (%s)", getattr(function, "__name__", "unknown"), type(error).__name__)

def schedule_user_registration(user) -> None:
    user_id = getattr(user, "id", None)
    if not isinstance(user_id, int):
        return
    now = time.monotonic()
    last_scheduled = _analytics_last_registered.get(user_id)
    if last_scheduled is not None and now - last_scheduled < ANALYTICS_REGISTRATION_COOLDOWN_SECONDS:
        return
    _analytics_last_registered[user_id] = now
    _schedule_analytics_task(
        _register_user_sync, user_id, getattr(user, "username", None), getattr(user, "first_name", None)
    )

def analytics_button_info(callback_data: str) -> tuple[str, str]:
    # Normalize callback payloads; never persist raw callback data or message content.
    if callback_data.startswith("cln:"):
        parts = callback_data.split(":")
        if len(parts) >= 4:
            action, value = parts[2], parts[3]
            if action == "zone" and value in {"kitchen", "kids", "clothes", "living", "everywhere"}:
                return "clean", f"zone_{value}"
            if action == "time" and value in {"5", "10", "15"}:
                return "clean", f"time_{value}"
            if action == "energy" and value in {"low", "normal", "high"}:
                return "clean", f"energy_{value}"
            actions = {"next_room": "next", "more": "alternative", "stop": "stop", "home": "back"}
            if action in actions:
                return "clean", actions[action]
            if action == "nextzone" and value in {"kitchen", "kids", "clothes", "living", "everywhere"}:
                return "clean", f"nextzone_{value}"
        return "clean", "clean_other_button"
    if callback_data.startswith("support:"):
        parts = callback_data.split(":")
        if len(parts) == 3 and parts[1] == "choose" and parts[2] in SUPPORT_SCENARIOS:
            return "support", f"choose_{parts[2]}"
        if callback_data == "support:choose_again":
            return "support", "choose_again"
        if callback_data == "support:home":
            return "support", "home"
        return "support", "support_other_button"
    if callback_data.startswith("kids:child:"):
        return "kids", "switch_child"
    if callback_data.startswith("kids:again:"):
        return "kids", "another_game"
    if callback_data == "kids:joint":
        return "kids", "joint_game"
    if callback_data.startswith("family_age:"):
        action = callback_data.split(":", 1)[1]
        if action in {"skip", "edit", "save", "cancel"}:
            return "family_profile", f"age_{action}"
        return "family_profile", "age_other_button"
    if callback_data.startswith("chaos:"):
        action = callback_data.split(":", 1)[1]
        if action in {"kitchen", "kids", "living", "bath", "menu"}:
            return "clean", f"chaos_{action}"
        return "clean", "chaos_other_button"
    known = {
        "menu_food": ("food", "menu_food"), "menu_clean": ("clean", "menu_clean"),
        "menu_plan": ("plan", "menu_plan"), "menu_support": ("support", "menu_support"),
        "menu_radiance": ("radiance", "menu_radiance"), "menu_kids": ("kids", "menu_kids"),
        "radiance:undertones": ("radiance", "undertones"),
        "radiance:retry": ("radiance", "retry_photo"),
        "radiance:cancel": ("radiance", "cancel"),
        "radiance:locked:wardrobe": ("radiance", "locked_wardrobe"),
        "radiance:locked:care": ("radiance", "locked_care"),
        "radiance:locked:suitable": ("radiance", "locked_suitable"),
        "radiance:interest:wardrobe": ("radiance", "interest_wardrobe"),
        "radiance:interest:care": ("radiance", "interest_care"),
        "radiance:interest:suitable": ("radiance", "interest_suitable"),
        "kids:story_pdf": ("kids", "story_pdf"),
        "kids:interest:story_pdf": ("kids", "interest_story_pdf"),
        "kids:cancel_age": ("kids", "cancel_age"),
        "menu:main": ("main", "main_menu"), "back_to_menu": ("main", "back_to_menu"),
        "another_food": ("food", "another_food"), "expand_details": ("food", "expand_details"),
    }
    return known.get(callback_data, ("other", "other_button"))

def schedule_analytics_event(telegram_user_id: int, event_name: str, section: str, button_id: str) -> None:
    _schedule_analytics_task(
        _insert_analytics_event_sync, telegram_user_id, event_name, section, button_id
    )

def _insert_analytics_event_sync(telegram_user_id: int, event_name: str, section: str, button_id: str) -> None:
    with _analytics_connect() as connection:
        connection.execute("""
            INSERT INTO public.bot_events (telegram_user_id, event_name, section, button_id)
            VALUES (%s, %s, %s, %s)
        """, (telegram_user_id, event_name, section, button_id))

def _read_stats_sync() -> dict:
    with _analytics_connect() as connection:
        row = connection.execute("""
            SELECT
                (SELECT COUNT(*) FROM public.bot_users)
                    + COALESCE((
                        SELECT legacy_guest_count
                        FROM public.bot_analytics_baseline
                        WHERE id = 1
                    ), 0) AS total_users,
                COUNT(*) FILTER (
                    WHERE first_seen_at >= now() - interval '24 hours'
                ) AS new_24h,
                COUNT(*) FILTER (
                    WHERE first_seen_at >= now() - interval '7 days'
                ) AS new_7d
            FROM public.bot_users
        """).fetchone()
        sections = connection.execute("""
            SELECT section, COUNT(*) AS clicks FROM public.bot_events
            WHERE occurred_at >= now() - interval '7 days'
            GROUP BY section ORDER BY clicks DESC, section LIMIT 5
        """).fetchall()
        buttons = connection.execute("""
            SELECT section, button_id, COUNT(*) AS clicks FROM public.bot_events
            WHERE occurred_at >= now() - interval '7 days'
            GROUP BY section, button_id ORDER BY clicks DESC, section, button_id LIMIT 5
        """).fetchall()
    return {"total_users": row[0], "new_24h": row[1], "new_7d": row[2],
            "popular_sections": sections, "popular_buttons": buttons}

def delete_user_data_from_database(user_id: int) -> None:
    # Сохраняем welcomed_users: сброс личных данных не должен повторно
    # отправлять уведомление об этом же человеке в канал.
    user_data_tables = ("user_names", "pending_user_names")
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
        stats = await asyncio.wait_for(asyncio.to_thread(_read_stats_sync), timeout=ANALYTICS_TASK_TIMEOUT_SECONDS)
        total_users = stats["total_users"]
        section_labels = {
            "main": "Главное меню", "food": "Накормить семью", "clean": "Разгрести хаос",
            "plan": "День по полочкам", "support": "Тёплая поддержка",
            "radiance": "Моё сияние", "kids": "Занять ребёнка",
            "family_profile": "Профиль семьи", "other": "Другие кнопки",
        }
        sections = stats["popular_sections"]
        buttons = stats["popular_buttons"]
        sections_text = "\n".join(
            f"• {html.escape(section_labels.get(section, section))}: <b>{clicks}</b>"
            for section, clicks in sections
        ) if sections else "• Пока нет данных"
        buttons_text = "\n".join(
            f"• {html.escape(section_labels.get(section, section))} / <code>{html.escape(button_id)}</code>: <b>{clicks}</b>"
            for section, button_id, clicks in buttons
        ) if buttons else "• Пока нет данных"
        stats_text = (
            "📊 <b>Статистика бота «Мама 24/7»</b>\n\n"
            f"👥 Всего уникальных пользователей: <b>{total_users}</b>\n"
            f"🆕 Новых за 24 часа: <b>{stats['new_24h']}</b>\n"
            f"📅 Новых за 7 дней: <b>{stats['new_7d']}</b>\n"
            f"🎯 До цели в 100: <b>{max(0, 100 - total_users)}</b>\n\n"
            "🌿 <b>Популярность разделов за 7 дней</b>\n"
            f"{sections_text}\n\n"
            "🖱 <b>Популярные кнопки за 7 дней</b>\n"
            f"{buttons_text}"
        )
        await message.answer(stats_text, parse_mode=ParseMode.HTML)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.warning("Stats query failed (%s)", type(error).__name__)
        await message.answer("Не удалось получить статистику из базы данных. Попробуй немного позже.")




RADIANCE_MENU_TEXT = (
    "✨ <b>Моё сияние</b>\n\n"
    "Твой личный AI-стилист и бьюти-помощник ✨\n"
    "Начнём с бесплатной ориентировочной палитры цветов. Остальные возможности пока закрыты."
)


def radiance_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌸 Подобрать мои оттенки (Бесплатно)", callback_data="radiance:undertones")],
        [InlineKeyboardButton(text="👗 Собрать образы из шкафа 🔒", callback_data="radiance:locked:wardrobe")],
        [InlineKeyboardButton(text="💄 Подобрать уход и косметику 🔒", callback_data="radiance:locked:care")],
        [InlineKeyboardButton(text="🛍️ Мне это подойдёт? 🔒", callback_data="radiance:locked:suitable")],
    ])


RADIANCE_LOCKED_CARDS = {
    "wardrobe": (
        "👗 <b>Образы из твоего шкафа</b>\n\n"
        "В будущем помощник сможет помогать сочетать вещи, собирать комплекты под разные случаи "
        "и находить новые комбинации из того, что у тебя уже есть."
    ),
    "care": (
        "💄 <b>Уход и косметика</b>\n\n"
        "Подбор базового ухода и косметических средств с учётом твоих предпочтений, "
        "привычного ритма и желаемого образа."
    ),
    "suitable": (
        "🛍️ <b>Мне это подойдёт?</b>\n\n"
        "Возможность обсудить вещь, оттенок или косметический продукт и понять, "
        "как он впишется в твой стиль."
    ),
}
RADIANCE_INTEREST_LABELS = {
    "wardrobe": "interest_wardrobe",
    "care": "interest_care",
    "suitable": "interest_suitable",
    "story_pdf": "interest_story_pdf",
}


def radiance_locked_keyboard(feature: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Хочу доступ", callback_data=f"radiance:interest:{feature}")],
        [InlineKeyboardButton(text="↩️ Назад к Моему сиянию", callback_data="menu_radiance")],
    ])


def kids_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Персональная книжка-сказка в PDF 🔒", callback_data="kids:story_pdf")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")],
    ])


def kids_result_keyboard(
    ages: list[dict],
    current_child_number: int | None = None,
    joint: bool = False,
) -> InlineKeyboardMarkup:
    """Navigation under a generated game; callback_data stays compact and profile-backed."""
    ordered = sorted(ages, key=lambda age: (kids_age_months(age), int(age["child_number"])))
    same_age_counts: dict[int, int] = {}
    for age in ordered:
        months = kids_age_months(age)
        same_age_counts[months] = same_age_counts.get(months, 0) + 1
    same_age_seen: dict[int, int] = {}
    rows = [[InlineKeyboardButton(
        text="🎲 Другая игра",
        callback_data="kids:again:all" if joint else f"kids:again:{current_child_number}",
    )]]
    for age in ordered:
        child_number = int(age["child_number"])
        months = kids_age_months(age)
        label = kids_picker_label(age)
        distinction = ""
        if same_age_counts[months] > 1:
            same_age_seen[months] = same_age_seen.get(months, 0) + 1
            ordinals = ("первый", "второй", "третий", "четвёртый", "пятый", "шестой")
            ordinal = ordinals[min(same_age_seen[months] - 1, len(ordinals) - 1)]
            distinction = f" · {ordinal} в списке"
        if not joint and child_number == current_child_number:
            continue
        rows.append([InlineKeyboardButton(
            text=f"{label} ({format_child_age(age)}){distinction}",
            callback_data=f"kids:child:{child_number}",
        )])
    if len(ordered) > 1 and not joint:
        rows.append([InlineKeyboardButton(text="🤝 Игра для всех", callback_data="kids:joint")])
    rows.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def radiance_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Попробовать другое фото", callback_data="radiance:retry")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")],
    ])

def kids_story_card_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Хочу доступ", callback_data="kids:interest:story_pdf")],
        [InlineKeyboardButton(text="↩️ Назад к играм", callback_data="menu_kids")],
    ])


# Keep recent activity and category per user + selected child (or joint-game context).
kids_last_activities: dict[tuple[int, str], str] = {}
kids_last_categories: dict[tuple[int, str], str] = {}
kids_last_activity_ids: dict[tuple[int, str], str] = {}
kids_generation_in_progress: set[int] = set()

KIDS_ACTIVITY_CATEGORIES = (
    ("think", "🧠 Подумать и разгадать", "Логическая задача, шифр, детективная загадка или данетка с однозначным решением."),
    ("create", "🎨 Придумать и создать", "Творчество из подручных вещей, сторителлинг, персонаж или дизайн-челлендж."),
    ("play", "🎲 Поиграть и посмеяться", "Словесный баттл, абсурдный юмор, игра на реакцию или викторина."),
    ("explore", "🔎 Найти и исследовать", "Безопасная фотоохота, домашний мини-квест, наблюдение или простой эксперимент."),
    ("together", "🤝 Сделать вместе", "Командный челлендж, семейный ритуал, общий проект или небольшое совместное дело."),
    ("calm", "🌿 Спокойно переключиться", "Спокойное сенсорное занятие, внимание к окружающему или мягкое переключение после школы/садика."),
)


def kids_activity_context_key(user_id: int, ages: list[dict], joint: bool = False) -> tuple[int, str]:
    if joint:
        return (user_id, "all")
    if not ages:
        return (user_id, "unknown")
    return (user_id, f"child:{int(ages[0]['child_number'])}")


def kids_activity_short_id(activity: str) -> str:
    """Create a compact title-based identifier for the most recently suggested activity."""
    cleaned = (activity or "").strip()
    first_line = cleaned.splitlines()[0] if cleaned else ""
    title_match = re.search(r"«([^»]{1,100})»", first_line)
    title = title_match.group(1) if title_match else first_line
    identifier = re.sub(r"[^a-zа-яё0-9]+", "-", title.casefold()).strip("-")
    return identifier[:48] or "activity"


def kids_next_activity_category(
    user_id: int | None,
    context: str,
    ages: list[dict],
) -> tuple[str, str, str]:
    """Choose an age-suitable category, then cycle through all six without repeating."""
    previous_key = kids_last_categories.get((user_id, context)) if user_id is not None else None
    by_key = {category[0]: category for category in KIDS_ACTIVITY_CATEGORIES}
    youngest = min((kids_age_months(age) for age in ages), default=84)
    if youngest < 36:
        eligible = ("create", "play", "explore", "together", "calm")
    elif youngest < 72:
        eligible = ("think", "create", "play", "explore", "together", "calm")
    else:
        eligible = tuple(by_key)

    if previous_key in eligible:
        index = eligible.index(previous_key)
        return by_key[eligible[(index + 1) % len(eligible)]]
    return by_key[random.choice(eligible)]


def kids_age_months(age: dict) -> int:
    value = int(age["age_value"])
    return value if age["age_unit"] == "months" else value * 12


def kids_age_band(months: int) -> tuple[str, str]:
    if months < 36:
        return ("до 3 лет", "Короткое сенсорное или тактильное занятие с крупными безопасными бытовыми предметами; постоянный присмотр взрослого, никаких мелких деталей, горячих жидкостей, химии или опасных опытов.")
    if months < 72:
        return ("3–5 лет", "Короткая игра с воображением, движением, цветами, формами и простыми безопасными предметами.")
    if months < 120:
        return ("6–9 лет", "Квесты, логические задачи, творчество, исследование и конструирование с понятными правилами.")
    if months < 156:
        return ("10–12 лет", "Более сложные головоломки, викторины, творческие челленджи и самостоятельные мини-проекты.")
    if months < 192:
        return ("13–15 лет", "Уважительный взрослый тон; интеллектуальные задачи, юмор, дизайн, музыка, творчество, исследования и командные игры. Не предлагай малышовые игры по умолчанию.")
    if months < 216:
        return ("16–17 лет", "Самостоятельные проекты, сложные логические задачи, творческие и практические челленджи, интеллектуальные и семейные активности без снисходительного тона.")
    return ("18 лет и старше", "Самостоятельный интеллектуальный, творческий или практический челлендж соответствующей сложности, без детского тона.")


def kids_picker_label(age: dict) -> str:
    months = kids_age_months(age)
    if months < 24:
        return "👶 Малыш"
    if months < 60:
        return "🧒 Кроха"
    if months < 120:
        return "🧩 Ребёнок"
    if months < 156:
        return "🎯 Старший"
    if months < 192:
        return "🎧 Подросток"
    if months >= 192:
        return "✨ Старший подросток"
    return "✨ Старший подросток"


def kids_picker_keyboard(ages: list[dict]) -> InlineKeyboardMarkup:
    ordered = sorted(ages, key=lambda age: (kids_age_months(age), int(age["child_number"])))
    same_age_counts: dict[int, int] = {}
    for age in ordered:
        months = kids_age_months(age)
        same_age_counts[months] = same_age_counts.get(months, 0) + 1
    same_age_seen: dict[int, int] = {}
    buttons = []
    for age in ordered:
        months = kids_age_months(age)
        label = kids_picker_label(age)
        distinction = ""
        if same_age_counts[months] > 1:
            same_age_seen[months] = same_age_seen.get(months, 0) + 1
            ordinals = ("первый", "второй", "третий", "четвёртый", "пятый", "шестой")
            ordinal = ordinals[min(same_age_seen[months] - 1, len(ordinals) - 1)]
            distinction = f" · {ordinal} в списке"
        buttons.append([
            InlineKeyboardButton(
                text=f"{label} ({format_child_age(age)}){distinction}",
                callback_data=f"kids:child:{age['child_number']}",
            )
        ])
    joint_label = "🤝 Общая игра для двоих" if len(ages) == 2 else "🤝 Общая игра для всех"
    buttons.append([InlineKeyboardButton(text=joint_label, callback_data="kids:joint")])
    buttons.append([InlineKeyboardButton(text="↩️ Назад в меню", callback_data="kids:cancel_age")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

KIDS_TEEN_FALLBACKS = [
    "🎧 Предложи подростку музыкальный баттл.\n\nСпроси: «Какая песня лучше всего подошла бы к финалу фильма о твоей жизни — и почему?» Попроси назвать один трек и объяснить выбор в двух фразах.",
    "🕵️ Загадай подростку логическую загадку про три коробки: на них написано «яблоки», «груши» и «смесь», но все надписи неверные.\n\nСпроси: «Как, достав один фрукт именно из коробки с надписью “смесь”, определить содержимое всех трёх?» Предложи объяснить ход мысли и вместе проверить решение.\n\n💡 Отгадка для мамы: из коробки «смесь» достали один вид фрукта, значит в ней только он; две оставшиеся коробки определяются по запрету на верные надписи.",
    "🎨 Предложи подростку творческий челлендж.\n\nСкажи: «Придумай постер к несуществующему фильму, используя только три цвета и название из пяти слов». Потом попроси объяснить жанр и настроение фильма."
]


def kids_activity_fallback(age: dict) -> str:
    months = kids_age_months(age)
    if months >= 156:
        return random.choice(KIDS_TEEN_FALLBACKS)
    if months >= 120:
        return random.choice([
            "🕵️ Предложи ребёнку логический детектив.\n\nСпроси: «У Ани, Бори и Вики по одному питомцу: кот, рыбка или попугай. У Ани кот. У Бори не рыбка. У Вики не попугай. Кто у кого?» Попроси объяснить решение, не угадывая наугад.\n\n💡 Отгадка для мамы: у Ани кот, у Бори попугай, у Вики рыбка.",
            "🔐 Предложи ребёнку словесный челлендж.\n\nСкажи: «Зашифруй моё имя, заменив каждую букву следующей буквой русского алфавита, и дай мне разгадать». Заранее договоритесь, считать ли «ё» отдельной буквой.",
            "🎯 Устрой викторину наоборот.\n\nПредложи ребёнку выбрать тему и придумать три вопроса разной сложности, а затем ответьте друг другу и вместе проверьте спорные факты."
        ])
    pool_key = "baby" if months < 18 else "toddler" if months < 60 else "preschool" if months < 120 else "older"
    return re.sub(r"</?b>", "", random.choice(KIDS_ACTIVITY_POOLS[pool_key]))


def format_kids_activity_html(text: str, age_caption: str) -> str:
    """Escape generated text and add only controlled Telegram HTML, including spoilers."""
    cleaned = (text or "").strip()
    if not cleaned:
        cleaned = f"🎯 «Игра на минутку» ({age_caption})"
    lines = cleaned.splitlines()
    first = lines[0].strip()
    if not re.match(r"^[^\w\s]{1,4}\s*«.+»\s*\(.+\)$", first):
        lines.insert(0, f"🎯 «Игра на минутку» ({age_caption})")
    escaped_lines = []
    for index, line in enumerate(lines):
        # Keep the model output plain text; construct spoiler tags only in code.
        answer_match = re.match(
            r"^\s*💡\s*Отгадка для мамы\s*:\s*(.*?)\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if answer_match:
            answer = answer_match.group(1).strip()
            if answer:
                escaped_answer = html.escape(answer, quote=False)
                escaped_lines.append(
                    f"💡 <b>Отгадка для мамы:</b> <tg-spoiler>{escaped_answer}</tg-spoiler>"
                )
            else:
                escaped_lines.append(
                    "💡 <b>Отгадка для мамы:</b> <tg-spoiler>Ответ не указан.</tg-spoiler>"
                )
            continue
        escaped_line = html.escape(line, quote=False)
        if index == 0:
            escaped_line = f"<b>{escaped_line}</b>"
        else:
            escaped_line = re.sub(r"«([^«»\n]{1,700})»", r"«<b>\1</b>»", escaped_line)
        escaped_lines.append(escaped_line)
    return "\n".join(escaped_lines)

class KidsActivityValidationError(ValueError):
    """A generated riddle failed the answer-format or determinacy checks."""


def kids_activity_answer_error(activity: str) -> str | None:
    """Return a validation reason for a malformed riddle answer; leave ordinary games alone."""
    lines = [line.strip() for line in (activity or "").splitlines() if line.strip()]
    answer_indexes = [
        index for index, line in enumerate(lines)
        if re.match(r"^💡\s*Отгадка для мамы\s*:", line, flags=re.IGNORECASE)
    ]
    looks_like_riddle = bool(re.search(
        r"загадк|детектив|данетк|логическ(?:ая|ую|ой|ий|ое)?\s+(?:задач|загадк)|улика|\bдано\b",
        activity or "",
        flags=re.IGNORECASE,
    ))
    if not answer_indexes:
        return "для загадки отсутствует блок отгадки" if looks_like_riddle else None
    if len(answer_indexes) != 1:
        return "должен быть ровно один блок отгадки"
    index = answer_indexes[0]
    if index != len(lines) - 1:
        return "отгадка должна быть последним непустым абзацем"
    answer = re.sub(r"^💡\s*Отгадка для мамы\s*:\s*", "", lines[index], flags=re.IGNORECASE).strip()
    if not answer:
        return "отгадка пустая"
    if "(" in answer or ")" in answer:
        return "в отгадке запрещены скобки"
    if re.search(r"</?\s*[a-z][^>]*>", answer, flags=re.IGNORECASE):
        return "в тексте отгадки запрещены HTML-теги"
    forbidden = (
        r"\bили\b",
        r"\bлибо\b",
        r"хотя\s+точнее",
        r"если\s+точнее",
        r"в\s+классической\s+задаче",
        r"\bвозможно\b",
        r"\bвероятно\b",
        r"может\s+быть",
        r"скорее\s+всего",
        r"наверное",
        r"предположительно",
        r"одна\s+из\s+версий",
        r"альтернативн",
    )
    if any(re.search(pattern, answer, flags=re.IGNORECASE) for pattern in forbidden):
        return "в отгадке есть запрещённая конструкция или альтернативная версия"
    words = re.findall(r"\b[А-Яа-яЁёA-Za-z0-9]+\b", answer)
    if len(words) > 15:
        return f"в отгадке {len(words)} слов, максимум 15"
    sentence_marks = re.findall(r"[.!?]+(?=\s|$)", answer)
    if len(sentence_marks) != 1 or not answer.endswith("."):
        return "отгадка должна быть одним утвердительным предложением с точкой"
    if "?" in answer or "!" in answer:
        return "отгадка должна быть утвердительной, не вопросом и не восклицанием"
    return None


def generate_kids_activity_sync(
    ages: list[dict],
    previous: str | None = None,
    category: tuple[str, str, str] | None = None,
) -> str:
    age_lines = []
    for index, age in enumerate(ages, start=1):
        months = kids_age_months(age)
        band, guidance = kids_age_band(months)
        age_lines.append(
            f"Участник {index}: точный возраст {format_child_age(age)} ({months} месяцев), "
            f"возрастная группа {band}. Правила: {guidance}"
        )
    joint = len(ages) > 1
    teen_present = any(156 <= kids_age_months(age) < 192 for age in ages)
    prompt = (
        "Ты — помощник для мамы или другого взрослого, который выбирает занятие для ребёнка. "
        "Пиши ответ именно взрослому, а не ребёнку: мама должна сразу понять, что предложить и какие слова сказать. "
        "Придумай ОДНО конкретное, живое, безопасное занятие на 5–15 минут. Оно должно читаться по диагонали за 5 секунд. "
        "Первая строка ОБЯЗАТЕЛЬНО: короткий интересный заголовок с одним уместным эмодзи, названием в «ёлочках» "
        "и точным возрастом, например: 🕵️ «Секретный агент» (7 лет). Для совместной игры укажи возраста участников. "
        "Дальше 2–3 очень коротких абзаца без формальных разделов и длинных вступлений. Используй умеренно смысловые "
        "эмодзи ✨, 📝, 💡, 🎯. Сначала коротко предложи маме идею. Затем дай готовую реплику, вопрос или затравку, "
        "которую мама может сразу произнести или переслать ребёнку; обязательно заключи эту реплику в «ёлочки». "
        "Последний короткий абзац — только если полезно: как продолжить интерес. Не пиши разделы «Что понадобится», "
        "«Формат участия», «Правила по шагам», «Как понять, что игра закончена». "
        "Используй точный возраст каждого участника и не теряй возраст при выборе кнопки.\n\n"
        + "\n".join(age_lines)
        + "\n\nОдна выбранная категория для этого занятия: "
        + (f"{category[1]} — {category[2]}" if category else "выбери наиболее подходящую возрасту из шести категорий")
        + ". Категории: "
        + "; ".join(f"{label}: {description}" for _, label, description in KIDS_ACTIVITY_CATEGORIES)
        + ". Строго соблюдай выбранную категорию; не повторяй прошлую идею под новым названием. "
        + "\n\nНе выдумывай интересы и не делай предположений по полу. Если ребёнок может безопасно играть сам, "
        "это допустимо, но обращение и инструкция в ответе всё равно адресованы взрослому. "
        "Загадки и задания должны иметь логичное решение, быть выполнимыми и безопасными. Не придумывай "
        "заведомо неразрешимые загадки, опасные эксперименты, задания с огнём, острыми инструментами или риском падения. "
        "Если занятие содержит загадку, детективную историю, данетку или логическую задачу, используй только "
        "условие, в котором достаточно фактов для одного проверяемого ответа. Ответ должен прямо следовать из описанных "
        "фактов без внешних предположений и скрытых обстоятельств; согласуй условие, вопрос и ответ. Неоднозначную загадку "
        "замени другой до выдачи. Перед ответом проверь логическую согласованность. "
        "Отгадка ОБЯЗАТЕЛЬНО должна быть ровно одним коротким утвердительным предложением, максимум 15 слов, "
        "с итоговым ответом и только при необходимости краткой причиной. Запрещены рассуждения вслух, черновики, "
        "сомнения, самоисправления, альтернативные версии, скобки с альтернативными объяснениями и повтор условия вместо ответа. "
        "В отгадке запрещены слова и конструкции: «или», «хотя точнее», «если точнее», «в классической задаче», "
        "«возможно», «вероятно», «может быть», а также любые эквивалентные выражения сомнения или выбора вариантов. "
        "Сначала выдай законченную историю и вопрос, не раскрывай ответ раньше времени. Последним непустым абзацем "
        "добавь строго одну строку: «💡 Отгадка для мамы: одно короткое утвердительное предложение.» "
        "Не добавляй после неё никаких строк. Это обязательно для загадок, детективов, данеток и логических задач для любого "
        "возраста, включая подростков и совместные семейные игры. Для занятия без загадки или логической задачи отгадку НЕ добавляй. "
        "Не используй Markdown или HTML-теги: оформление Telegram добавит код бота. "
        "Верни только готовый текст игры."
        + ("\n\nДля подростка 13–15 лет выбирай уместные форматы: детективная загадка с логичной разгадкой, "
           "логическая дилемма, викторина о кино или музыке, словесная дуэль или творческий челлендж. "
           "Не предлагай малышовые игры по умолчанию и не говори снисходительно." if teen_present else "")
        + ("\n\nЭто совместная игра для всех перечисленных возрастов. Предложи одну общую цель и разные роли "
           "или уровни сложности; учитывай безопасность самого младшего." if joint else "")
        + (f"\n\nНе повторяй прошлое занятие: {previous[:500]}" if previous else "")
        + ("\n\nДля любого участника 13–17 лет не предлагай примитивные детские игры (детские прятки, "
           "пантомимы для малышей или изображение персонажей без слов), если подросток сам этого не попросил." 
           if any(156 <= kids_age_months(age) < 216 for age in ages) else "")
    )
    last_error = "неизвестная ошибка проверки"
    for attempt in range(2):
        attempt_prompt = prompt
        if attempt:
            attempt_prompt += (
                "\n\nИСПРАВЬ ПРЕДЫДУЩИЙ ВАРИАНТ. Ошибка проверки отгадки: "
                + last_error
                + ". Перепиши загадку целиком так, чтобы ответ однозначно следовал из условия. "
                "Отгадка — одно утвердительное предложение до 15 слов, без альтернатив, сомнений, скобок "
                "и запрещённых формулировок. Верни только готовую игру."
            )
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=attempt_prompt,
            config=types.GenerateContentConfig(temperature=0.4 if attempt else 0.7),
        )
        activity = (response.text or "").strip()
        last_error = kids_activity_answer_error(activity)
        if last_error is None:
            return activity
    raise KidsActivityValidationError(
        "Gemini не смогла создать загадку с короткой однозначной отгадкой"
    )


async def kids_activity_for_age(age: dict, user_id: int | None = None) -> str:
    context_key = kids_activity_context_key(user_id, [age]) if user_id is not None else None
    context = context_key[1] if context_key else f"child:{int(age['child_number'])}"
    previous = kids_last_activities.get(context_key) if context_key is not None else None
    category = kids_next_activity_category(user_id, context, [age])
    try:
        activity = await asyncio.wait_for(
            asyncio.to_thread(generate_kids_activity_sync, [age], previous, category),
            timeout=35,
        )
        if not activity:
            raise ValueError("Gemini returned an empty activity")
    except asyncio.CancelledError:
        raise
    except KidsActivityValidationError as error:
        logger.warning("Kids activity answer validation failed (%s); using a non-riddle fallback", type(error).__name__)
        activity = (
            f"🎨 «Три цвета» ({format_child_age(age)})\n"
            "Предложи ребёнку нарисовать необычный дом, используя три цвета. "
            "Попроси придумать дому название."
        )
    except Exception as error:
        logger.warning("Kids Gemini generation failed (%s); using age-appropriate fallback", type(error).__name__)
        activity = kids_activity_fallback(age) + (
            "\n\n💡 Сейчас с генерацией заминка, поэтому это запасной безопасный вариант. "
            "Кнопки ниже остаются доступны."
        )
    if user_id is not None and context_key is not None:
        kids_last_activities[context_key] = activity
        kids_last_categories[context_key] = category[0]
        kids_last_activity_ids[context_key] = kids_activity_short_id(activity)
    return format_kids_activity_html(activity, format_child_age(age))


async def kids_joint_activity(ages: list[dict], user_id: int | None = None) -> str:
    context_key = kids_activity_context_key(user_id, ages, joint=True) if user_id is not None else None
    previous = kids_last_activities.get(context_key) if context_key is not None else None
    category = kids_next_activity_category(user_id, "all", ages)
    try:
        activity = await asyncio.wait_for(
            asyncio.to_thread(generate_kids_activity_sync, ages, previous, category),
            timeout=35,
        )
        if not activity:
            raise ValueError("Gemini returned an empty joint activity")
    except asyncio.CancelledError:
        raise
    except KidsActivityValidationError as error:
        logger.warning("Joint kids answer validation failed (%s); using a non-riddle fallback", type(error).__name__)
        ages_caption = " + ".join(format_child_age(age) for age in ages)
        activity = (
            f"🎨 «Три цвета» ({ages_caption})\n"
            "Предложите всем вместе нарисовать необычный дом, используя три цвета. "
            "Пусть каждый добавит одну деталь."
        )
    except Exception as error:
        logger.warning("Joint kids Gemini generation failed (%s); using safe fallback", type(error).__name__)
        youngest = min(ages, key=kids_age_months)
        activity = kids_activity_fallback(youngest) + (
            "\n\n💡 Сейчас с генерацией заминка, поэтому это запасной безопасный вариант для всех. "
            "Кнопки ниже остаются доступны."
        )
    if user_id is not None and context_key is not None:
        kids_last_activities[context_key] = activity
        kids_last_categories[context_key] = category[0]
        kids_last_activity_ids[context_key] = kids_activity_short_id(activity)
    ages_caption = " + ".join(format_child_age(age) for age in ages)
    return format_kids_activity_html(activity, ages_caption)

KIDS_ACTIVITY_POOLS = {
    "baby": [
        "👶 <b>Игра на минутку: «Ку-ку с платочком»</b>\n\nСядь рядом и ненадолго прикрой лицо ладонями или лёгким большим платочком, затем покажись: «Ку-ку!» Не накрывай лицо малыша и сразу убери платочек. Всё время оставайся рядом.",
        "🌿 <b>Игра на минутку: «Послушай шуршание»</b>\n\nПошурши крупным листом бумаги или тканью на расстоянии, дай малышу послушать и повтори звук с другой стороны. Не оставляй материал в руках без присмотра и не используй пакеты или плёнку.",
        "👏 <b>Игра на минутку: «Ладушки»</b>\n\nМягко спой знакомую песенку и похлопай в ладоши в её ритм. Если малышу нравится, помоги ему повторить движение, не настаивая.",
        "⚽ <b>Игра на минутку: «Прокати мячик»</b>\n\nСядь напротив малыша на полу и медленно прокати ему большой лёгкий мяч. Подожди, пока он коснётся мяча или попробует вернуть его. Только крупный мяч и постоянный присмотр.",
        "🎵 <b>Игра на минутку: «Где звенит?»</b>\n\nТихонько напой короткую мелодию или похлопай в ладоши сначала справа, затем слева, чтобы малыш повернулся к звуку. Не используй громкие звуки.",
        "😊 <b>Игра на минутку: «Зеркальце»</b>\n\nУлыбнись малышу, покажи язык или надуй щёки и дай ему время ответить мимикой. Повторяй то, что ему интересно, без спешки."
    ],
    "toddler": [
        "🧽 <b>Игра на минутку: «Башня из губок»</b>\n\nВозьми 2–3 чистые большие новые губки для посуды без упаковки и вместе сложите башню, а потом осторожно уроните её. Только под присмотром взрослого; если ребёнок тянет губки в рот, выбери игру без предметов.",
        "🧸 <b>Игра на минутку: «Где спрятался мишка?»</b>\n\nСпрячь крупную мягкую игрушку так, чтобы она была частично видна, и подсказывай: «Ищи рядом с подушкой!» Не прячь игрушку в пакетах или закрытых местах.",
        "🥄 <b>Игра на минутку: «Большая ложка»</b>\n\nПредложи переложить несколько крупных мягких игрушек или больших тканевых салфеток из одной пустой миски в другую большой ложкой. Используй только крупные безопасные предметы и следи, чтобы ребёнок не брал их в рот.",
        "🐻 <b>Игра на минутку: «Покажи, как мишка…»</b>\n\nПредложи мишке (или себе) потопать, потянуться, присесть и помахать рукой. Пусть малыш повторит одно движение или придумает своё.",
        "🚗 <b>Игра на минутку: «Машинка едет»</b>\n\nИзобрази голосом, как большая игрушечная машинка едет медленно, быстро и останавливается. Пусть малыш показывает руками, когда ехать и когда стоп. Игрушка должна быть крупной, без мелких деталей.",
        "🧺 <b>Игра на минутку: «Что в корзинке?»</b>\n\nПоложи в пустую корзину 2–3 знакомые крупные безопасные вещи, например большую мягкую игрушку и полотенце. Доставайте по одной и называйте. Не используй мелкие предметы и оставайся рядом.",
        "🎈 <b>Игра на минутку: «Повтори движение»</b>\n\nПохлопай, потопай, подними руки вверх, потом замри как статуя. Предложи малышу выбрать следующее движение. Играйте на свободном нескользком месте."
    ],
    "preschool": [
        "🛋️ <b>Игра на минутку: «Подушечная дорожка»</b>\n\nРазложи 2–3 подушки на полу и предложи перешагнуть через них или обойти змейкой. Убери скользкие предметы и держись рядом; не нужно прыгать с высоты.",
        "🎨 <b>Игра на минутку: «Охота за цветом»</b>\n\nНазови цвет и предложи найти в комнате три крупных предмета этого цвета. Можно показывать на них пальцем, ничего не доставая с полок.",
        "🍳 <b>Игра на минутку: «Шеф-повар»</b>\n\nПусть ребёнок придумает блюдо для игрушечного кафе: назовёт три воображаемых ингредиента и даст блюду смешное название. Настоящие ножи, плита и горячие продукты не нужны.",
        "🦁 <b>Игра на минутку: «Зоопарк дома»</b>\n\nНазови животное, а ребёнок пусть покажет, как оно двигается и звучит. Потом поменяйтесь ролями: теперь животное выбирает он.",
        "🔎 <b>Игра на минутку: «Найди по подсказке»</b>\n\nЗагадай крупный знакомый предмет: «Он мягкий, лежит на диване». Пусть ребёнок отгадает и найдёт его глазами или покажет пальцем.",
        "🏰 <b>Игра на минутку: «Архитектор»</b>\n\nПостройте из диванных подушек или крупных мягких кубиков дом для игрушки. Пусть ребёнок решит, где будет вход, а где окошко. Не залезайте на высокие конструкции.",
        "🧑‍🚀 <b>Игра на минутку: «Миссия на Луну»</b>\n\nПредложи пройти три безопасных задания: сделать три шага как космонавт, потянуться к звёздам и тихо приземлиться на ковёр. Избегайте мебели и скользкого пола.",
        "🧩 <b>Игра на минутку: «История из трёх слов»</b>\n\nВыбери три знакомых предмета в комнате и придумайте короткую историю, где все они встретились. Ребёнок может добавить самый смешной финал."
    ],
    "older": [
        "🕵️ <b>Игра на минутку: «Детектив цвета»</b>\n\nВыбери цвет и найди пять предметов этого цвета, не передвигая мебель и не залезая на высоту. Для усложнения назови, какой предмет самый большой.",
        "🎭 <b>Игра на минутку: «Угадай персонажа»</b>\n\nИзобрази героя или животное без слов, а ребёнок пусть угадает. Затем поменяйтесь ролями.",
        "🗺️ <b>Игра на минутку: «Карта сокровищ»</b>\n\nНарисуй на листе простой маршрут из трёх шагов по свободному месту комнаты и предложи пройти его. Не используй лестницы, острые предметы или скользкие поверхности.",
        "🎤 <b>Игра на минутку: «Реклама обычной вещи»</b>\n\nВыберите безопасный предмет в комнате и придумайте для него смешную рекламу из двух предложений. Чем необычнее польза, тем веселее!",
        "🧠 <b>Игра на минутку: «Три подсказки»</b>\n\nЗагадай предмет, а ребёнок должен отгадать его по трём признакам: цвет, форма и для чего он нужен. Потом поменяйтесь.",
        "🧑‍🍳 <b>Игра на минутку: «Меню для дракона»</b>\n\nПридумайте фантастическое меню для дракона из трёх блюд и объясните, почему он выбрал именно их. Ничего готовить не нужно.",
        "🎬 <b>Игра на минутку: «Немой фильм»</b>\n\nПокажи без слов, как собираешься в путешествие, а ребёнок пусть угадает действие. Потом он может поставить тебе свою загадку.",
        "🗝️ <b>Игра на минутку: «Домашний квест»</b>\n\nПридумай три словесные подсказки, ведущие к большой безопасной вещи на виду, например к диванной подушке. Пусть ребёнок разгадает маршрут, не открывая шкафы и не залезая на высоту.",
        "🔐 <b>Игра на минутку: «Секретный шифр»</b>\n\nЗашифруй короткое слово простым кодом: замени каждую букву следующей буквой алфавита или придумай значки для трёх букв. Предложи ребёнку разгадать послание на бумаге — без ножниц и мелких деталей.",
        "🧠 <b>Игра на минутку: «Что лишнее?»</b>\n\nНазови четыре слова, например «кошка, собака, заяц, кастрюля». Пусть ребёнок найдёт лишнее и объяснит почему, а потом придумает свой набор.",
        "🏗️ <b>Игра на минутку: «Строительный челлендж»</b>\n\nПредложи построить самую высокую устойчивую башню из крупных мягких кубиков или подушек, не вставая на мебель. Перед началом договоритесь, что конструкция должна быть безопасной и не выше колен."
    ]
}



async def start_radiance_flow(message: Message, user_id: int) -> None:
    radiance_states.pop(user_id, None)
    pending_kids_age.discard(user_id)
    support_sessions.pop(user_id, None)
    await message.answer(RADIANCE_MENU_TEXT, reply_markup=radiance_menu_keyboard(), parse_mode=ParseMode.HTML)


async def start_radiance_selfie(message: Message, user_id: int) -> None:
    pending_kids_age.discard(user_id)
    support_sessions.pop(user_id, None)
    radiance_states[user_id] = "waiting_for_selfie"
    await message.answer(
        "Сделай или отправь своё любимое селфи при дневном свете у окна (без фильтров и масок) 🌸\n\n"
        "А я помогу раскрыть твои природные краски и подберу цвета, которые подчеркнут твою естественную красоту! ✨",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Отмена / Назад", callback_data="radiance:cancel")],
        ]),
    )


def analyze_radiance_photo_sync(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    prompt = (
        "Ты — тёплая, естественная подруга, которая говорит на «ты». Пиши простым разговорным русским языком. "
        "Начни с короткого живого комплимента, который опирается ТОЛЬКО на конкретные детали, отчётливо видимые "
        "на этой фотографии. Не используй универсальные комплименты и не придумывай улыбку, чёлку, макияж, "
        "аксессуары, одежду или другие особенности, если их не видно или они различимы недостаточно. "
        "Не перечисляй возможные детали наугад. Если конкретное наблюдение ненадёжно, мягко опиши общее впечатление "
        "от образа без выдуманных подробностей. "
        "Не делай уверенных выводов о цвете глаз, оттенке кожи или волос, если освещение, фильтры, тени или качество "
        "снимка мешают их надёжно определить. В таком случае не угадывай: осторожно объясни, что именно на фото "
        "трудно оценить, сохраняя дружеский и поддерживающий тон. "
        "Не делай выводов о здоровье, состоянии кожи, заболеваниях, возрасте или личности по лицу. "
        "Если фото позволяет, простыми словами опиши только действительно заметные особенности; затем предложи "
        "4–5 понятных оттенков одежды или аксессуаров у лица с коротким объяснением и 1–2 оттенка для осторожной "
        "примерки. Используй обычные названия цветов, без профессионального сленга; не используй слова «нюанс» "
        "и «контрастность», если можно сказать проще. Не описывай недостатки внешности. "
        "Закончи короткой дружеской фразой. Не повторяй предупреждение о дневном свете, если оно уже прозвучало. "
        "Не обращайся на «вы», не используй фразы «Приветствую», «через призму колористики», "
        "«предварительный ориентир» и «контрольные оттенки». Если данных недостаточно, скажи об этом бережно "
        "и предложи повторить фото при более ровном освещении."
    )
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            ],
        )],
    )
    return (response.text or "").strip() or (
        "Не получилось уверенно подобрать палитру по этому кадру. Попробуй прислать фото при более ровном освещении 🌸"
    )

async def start_kids_flow(message: Message, user_id: int) -> None:
    radiance_states.pop(user_id, None)
    pending_kids_age.discard(user_id)
    support_sessions.pop(user_id, None)
    try:
        ages = await asyncio.to_thread(load_family_ages, user_id)
    except FamilyProfileUnavailable:
        await message.answer(
            "Не получилось проверить сохранённый возраст. Попробуй ещё раз чуть позже 🌿",
            reply_markup=MENU_KEYBOARD,
        )
        return
    if len(ages) == 1:
        await send_kids_activity(message, user_id, child_number=int(ages[0]["child_number"]))
        return
    if len(ages) > 1:
        await message.answer(
            "Кому подберём игру прямо сейчас? 🧸",
            reply_markup=kids_picker_keyboard(ages),
        )
        return
    pending_kids_age.add(user_id)
    await message.answer(
        "Сколько малышу лет или месяцев? Например: «8 месяцев» или «2 года». "
        "Я сохраню возраст в уже существующем профиле семьи и подберу безопасную игру на минутку 🌿",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Отмена / Назад", callback_data="kids:cancel_age")],
        ]),
    )


@dispatcher.callback_query(F.data.in_({"menu_radiance", "menu_kids"}))
async def process_radiance_kids_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    user_id = callback.from_user.id
    radiance_states.pop(user_id, None)
    pending_kids_age.discard(user_id)
    if callback.data == "menu_radiance":
        await start_radiance_flow(callback.message, user_id)
    else:
        await start_kids_flow(callback.message, user_id)


@dispatcher.callback_query(F.data == "radiance:undertones")
async def process_radiance_undertones(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is not None:
        await start_radiance_selfie(callback.message, callback.from_user.id)


@dispatcher.callback_query(F.data == "radiance:retry")
async def retry_radiance_selfie(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is not None:
        radiance_states.pop(callback.from_user.id, None)
        await start_radiance_selfie(callback.message, callback.from_user.id)


@dispatcher.callback_query(F.data == "radiance:cancel")
async def cancel_radiance_selfie(callback: CallbackQuery) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    radiance_states.pop(user_id, None)
    if callback.message is not None:
        await callback.message.answer(
            "Хорошо, разбор фото отменён 🌸",
            reply_markup=radiance_menu_keyboard(),
        )


@dispatcher.callback_query(F.data.startswith("radiance:locked:"))
async def show_radiance_locked_card(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None or not callback.data:
        return
    feature = callback.data.rsplit(":", 1)[-1]
    card = RADIANCE_LOCKED_CARDS.get(feature)
    if card is not None:
        await callback.message.answer(
            card,
            reply_markup=radiance_locked_keyboard(feature),
            parse_mode=ParseMode.HTML,
        )


@dispatcher.callback_query(F.data.startswith("radiance:interest:"))
async def radiance_interest(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None or not callback.data:
        return
    feature = callback.data.rsplit(":", 1)[-1]
    if feature not in RADIANCE_INTEREST_LABELS:
        return
    await callback.message.answer(
        "Спасибо за интерес! ✨ Я отметила твой запрос. Сейчас доступ ещё не подключён, "
        "и никаких списаний или покупок не происходит."
    )


async def send_kids_activity(
    message: Message,
    user_id: int,
    child_number: int | None = None,
    joint: bool = False,
) -> None:
    if user_id in kids_generation_in_progress:
        await message.answer("🎲 Уже придумываю игру — секундочку ✨")
        return
    kids_generation_in_progress.add(user_id)
    status_message = await message.answer("🎲 Придумываю новый вариант… ✨")
    try:
        ages = await asyncio.to_thread(load_family_ages, user_id)
        if joint:
            if len(ages) < 2:
                raise ValueError("joint game requires at least two current profile ages")
            result = await kids_joint_activity(ages, user_id)
            keyboard = kids_result_keyboard(ages, joint=True)
        else:
            selected_age = next((age for age in ages if int(age["child_number"]) == child_number), None)
            if selected_age is None:
                raise LookupError("selected child is no longer present in family profile")
            result = await kids_activity_for_age(selected_age, user_id)
            keyboard = kids_result_keyboard(ages, current_child_number=int(selected_age["child_number"]))
        await status_message.edit_text(result, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except asyncio.CancelledError:
        raise
    except (FamilyProfileUnavailable, LookupError, ValueError) as error:
        logger.warning("Kids navigation/generation setup failed (%s)", type(error).__name__)
        try:
            ages = await asyncio.to_thread(load_family_ages, user_id)
        except Exception:
            ages = []
        keyboard = kids_result_keyboard(ages, child_number, joint) if ages else InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")]]
        )
        await status_message.edit_text(
            "Не получилось подобрать игру сейчас 🙈 Попробуй ещё раз или вернись в главное меню.",
            reply_markup=keyboard,
        )
    finally:
        kids_generation_in_progress.discard(user_id)


@dispatcher.callback_query(F.data.startswith("kids:child:"))
async def choose_kids_child(callback: CallbackQuery) -> None:
    if callback.message is None or not callback.data:
        await callback.answer()
        return
    try:
        child_number = int(callback.data.rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer("Не удалось определить ребёнка", show_alert=True)
        return
    if callback.from_user.id in kids_generation_in_progress:
        await callback.answer("Уже придумываю игру ✨")
        return
    await callback.answer("🎲 Подбираю игру…")
    await send_kids_activity(callback.message, callback.from_user.id, child_number=child_number)


@dispatcher.callback_query(F.data.startswith("kids:again:"))
async def repeat_kids_game(callback: CallbackQuery) -> None:
    if callback.message is None or not callback.data:
        await callback.answer()
        return
    user_id = callback.from_user.id
    if user_id in kids_generation_in_progress:
        await callback.answer("Уже придумываю игру ✨")
        return
    target = callback.data.rsplit(":", 1)[-1]
    await callback.answer("🎲 Ищу другой вариант…")
    if target == "all":
        await send_kids_activity(callback.message, user_id, joint=True)
        return
    try:
        child_number = int(target)
    except ValueError:
        await callback.message.answer("Не получилось определить возраст. Открой раздел ещё раз 🌿", reply_markup=MENU_KEYBOARD)
        return
    await send_kids_activity(callback.message, user_id, child_number=child_number)


@dispatcher.callback_query(F.data == "kids:joint")
async def choose_kids_joint_game(callback: CallbackQuery) -> None:
    if callback.message is None:
        await callback.answer()
        return
    if callback.from_user.id in kids_generation_in_progress:
        await callback.answer("Уже придумываю игру ✨")
        return
    await callback.answer("🤝 Придумываю игру для всех…")
    await send_kids_activity(callback.message, callback.from_user.id, joint=True)


@dispatcher.callback_query(F.data == "kids:story_pdf")
async def show_kids_story_card(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            "📖 <b>Персональная книжка-сказка в PDF</b>\n\n"
            "В будущем можно будет создать добрую сказку с именем ребёнка и иллюстрациями, "
            "подходящую его возрасту. Эта возможность пока закрыта — ничего покупать сейчас не нужно.",
            reply_markup=kids_story_card_keyboard(),
            parse_mode=ParseMode.HTML,
        )


@dispatcher.callback_query(F.data == "kids:interest:story_pdf")
async def kids_story_interest(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            "Спасибо за интерес к книжке-сказке! 📖✨ Я отметила запрос. "
            "Доступ пока не подключён, списаний и покупок нет."
        )


@dispatcher.callback_query(F.data == "kids:cancel_age")
async def cancel_kids_age(callback: CallbackQuery) -> None:
    await callback.answer()
    pending_kids_age.discard(callback.from_user.id)
    if callback.message is not None:
        await callback.message.answer("Хорошо, вернулись в меню 🌿", reply_markup=MENU_KEYBOARD)


@dispatcher.message(F.photo)
async def handle_admin_photo(message: Message) -> None:
    if message.from_user is None or not message.photo:
        return
    user_id = message.from_user.id
    if radiance_states.get(user_id) == "waiting_for_selfie":
        radiance_states.pop(user_id, None)
        status_message = await message.answer(
            "Секундочку, любуюсь твоим фото и подбираю идеальную палитру... ✨"
        )
        try:
            photo_buffer = io.BytesIO()
            await bot.download(message.photo[-1], destination=photo_buffer)
            image_bytes = photo_buffer.getvalue()
            if not image_bytes:
                raise ValueError("empty photo payload")
            result = await asyncio.wait_for(
                asyncio.to_thread(analyze_radiance_photo_sync, image_bytes, "image/jpeg"),
                timeout=35,
            )
            try:
                await status_message.edit_text(result, reply_markup=radiance_result_keyboard())
            except Exception as edit_error:
                logger.warning("Could not edit radiance status (%s); sending result separately", type(edit_error).__name__)
                await message.answer(result, reply_markup=radiance_result_keyboard())
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Radiance photo analysis failed (%s)", type(error).__name__)
            error_text = "Не получилось разобрать фото сейчас 🙈 Попробуй ещё раз чуть позже или пришли фото при более ровном освещении."
            try:
                await status_message.edit_text(error_text, reply_markup=radiance_result_keyboard())
            except Exception as edit_error:
                logger.warning("Could not edit radiance error status (%s)", type(edit_error).__name__)
                await message.answer(error_text, reply_markup=radiance_result_keyboard())
        return
    await message.answer(
        "Какая чудесная фотография! 🌸 Но разбор внешности и стиля живёт у нас в отдельном домике. "
        "Нажми кнопку «✨ Моё сияние» в меню 👇"
    )
    # Технический file_id показываем только администратору в личном чате.
    if user_id == ADMIN_ID and message.chat.type == "private":
        await message.answer(
            f"Вот file_id твоего фото:\n<code>{html.escape(message.photo[-1].file_id)}</code>",
            parse_mode=ParseMode.HTML,
        )

@dispatcher.message(Command("testfoodphoto"))
async def handle_test_food_photos(message: Message) -> None:
    """Admin-only diagnostic: test every configured food photo ID in Telegram."""
    if (
        message.from_user is None
        or message.from_user.id != ADMIN_ID
        or message.chat.type != "private"
    ):
        return

    await message.answer("Проверяю все 10 фото по очереди. Успешные пришлю сюда 🌿")
    results = []
    for index, photo_id in enumerate(FOOD_BANNERS, start=1):
        try:
            await message.answer_photo(
                photo=photo_id,
                caption=f"Фото {index}/10 — file_id работает ✅",
            )
            results.append(f"{index}: OK")
        except Exception as error:
            logger.exception(
                "Food photo diagnostic failed for index %s (file_id ending %s)",
                index,
                photo_id[-8:],
            )
            short_error = str(error).replace("\\n", " ")[:180]
            results.append(f"{index}: ОШИБКА — {type(error).__name__}: {short_error}")

    report = "Результат проверки фото:\\n" + "\\n".join(results)
    for start in range(0, len(report), 3500):
        await message.answer(report[start : start + 3500])


def choose_banner(banner_ids: list[str] | tuple[str, ...] | None) -> str | None:
    """Выбирает случайный непустой Telegram file_id; пустые заглушки игнорируются."""
    available = [item.strip() for item in (banner_ids or []) if isinstance(item, str) and item.strip()]
    return random.choice(available) if available else None


async def answer_with_banner(
    message: Message,
    text: str,
    banner_ids: list[str] | tuple[str, ...] | None,
    reply_markup=None,
    parse_mode: ParseMode | str | None = ParseMode.HTML,
) -> Message:
    """Пробует все доступные фото по очереди; текст — только если ни одно не отправилось."""
    available = [
        item.strip()
        for item in (banner_ids or [])
        if isinstance(item, str) and item.strip()
    ]
    # Сохраняем исходный порядок: фото показываются по очереди.
    for photo in available:
        try:
            return await message.answer_photo(
                photo=photo,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        except Exception as error:
            logger.exception(
                "Could not send banner photo (file_id ending %s)",
                photo[-8:],
            )

    if available:
        logger.error("All %s banner photo IDs failed; sending text fallback", len(available))
    return await message.answer(
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )


async def replace_callback_message(callback: CallbackQuery) -> None:
    """Удаляет старое сообщение с кнопками, чтобы повторные нажатия не засоряли чат."""
    if callback.message is None:
        return
    try:
        await callback.message.delete()
    except Exception as error:
        logger.debug("Could not delete previous callback message: %s", error)


@dispatcher.message(CommandStart())
async def handle_start(message: Message) -> None:
    if message.from_user is None:
        return

    user_id = message.from_user.id
    support_sessions.pop(user_id, None)
    radiance_states.pop(user_id, None)
    pending_kids_age.discard(user_id)

    # Берём имя из Telegram и убираем лишнее, если там смайлы или цифры
    raw_name = (message.from_user.first_name or "").strip()
    clean_name = raw_name if raw_name.isalpha() and 2 <= len(raw_name) <= 20 else ""
    user_names[user_id] = clean_name

    is_new_user = False
    guest_count = 0
    try:
        with sqlite3.connect(STATE_DB_PATH) as conn:
            cursor = conn.cursor()
            # Проверяем оба реестра ДО любой отправки в канал.
            cursor.execute(
                "SELECT 1 FROM user_names WHERE user_id = ?",
                (user_id,),
            )
            exists_in_user_names = cursor.fetchone() is not None
            cursor.execute(
                "SELECT 1 FROM welcomed_users WHERE user_id = ?",
                (user_id,),
            )
            already_welcomed = cursor.fetchone() is not None
            is_new_user = not (exists_in_user_names or already_welcomed)

            cursor.execute(
                "INSERT INTO user_names (user_id, name) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET name = excluded.name",
                (user_id, clean_name or "Мама"),
            )
            # Атомарная защита от двух почти одновременных /start одного человека.
            cursor.execute(
                "INSERT OR IGNORE INTO welcomed_users (user_id) VALUES (?)",
                (user_id,),
            )
            welcome_record_created = cursor.rowcount == 1
            is_new_user = is_new_user and welcome_record_created

            # Фиксируем запись сразу, не полагаясь на закрытие соединения.
            conn.commit()

            cursor.execute("SELECT COUNT(DISTINCT user_id) FROM welcomed_users")
            current_unique_in_db = cursor.fetchone()[0]
            guest_count = current_unique_in_db + START_OFFSET
    except Exception as err:
        logger.warning("Could not save or count start user: %s", err)

    if is_new_user:
        try:
            user_tag = (
                f"@{message.from_user.username}"
                if message.from_user.username
                else "без никнейма"
            )
            goal = 100
            percent = min(100, int((guest_count / goal) * 100))
            filled = int(percent / 10)
            bar = "█" * filled + "░" * (10 - filled)
            left = max(0, goal - guest_count)
            notification_text = (
                "🌸 <b>Новая гостья в домике!</b>\n\n"
                f"👤 Имя: <b>{clean_name or 'Мама'}</b>\n"
                f"🔗 Тег: {user_tag}\n"
                f"🆔 ID: <code>{user_id}</code>\n\n"
                f"📊 <b>Она уже {guest_count}-я по счёту!</b> 🎯\n"
                f"[{bar}] {percent}%\n"
                f"⏳ До цели в 100 мам осталось: <b>{left}</b>"
            )
            await message.bot.send_message(
                -1004353307194,
                notification_text,
                parse_mode=ParseMode.HTML,
            )
        except (genai_errors.APIError, Exception) as log_err:
            logger.warning("Could not send new-user notification to channel: %s", log_err)

    await answer_with_banner(
        message,
        START_CAPTION,
        BANNER_START,
        reply_markup=inline_kb,
        parse_mode=ParseMode.HTML,
    )

@dispatcher.callback_query(F.data.in_({"menu_food", "menu_clean", "menu_plan", "menu_support"}))
async def process_start_action(callback: CallbackQuery) -> None:
    # Сразу закрываем индикатор ожидания на нажатой кнопке.
    await callback.answer()
    if callback.message is None:
        return
    radiance_states.pop(callback.from_user.id, None)
    pending_kids_age.discard(callback.from_user.id)
    if callback.data == "menu_clean":
        support_sessions.pop(callback.from_user.id, None)
        await replace_callback_message(callback)
        await start_chaos_flow(callback.message)
        return
    if callback.data == "menu_support":
        await replace_callback_message(callback)
        await start_support_flow(callback.message, request_user_id=callback.from_user.id)
        return

    support_sessions.pop(callback.from_user.id, None)
    prompts_map = {
        "menu_food": "Предложи разнообразное, простое и недорогое блюдо для всей семьи из обычных продуктов. Минимум активного времени у плиты, желательно 15-30 минут. Не повторяй блюда из нашей предыдущей переписки. В конце спроси, какие продукты уже есть дома, чтобы подобрать рецепт из них.",
        "menu_plan": "Составь тёплый и гибкий план именно для мамы: блоки заботы о детях, домашних дел и отдыха. Учитывай только известный контекст о возрасте детей, режиме, школе, садике и занятиях. Если известен младенец или малыш, оставь гибкие окна для кормлений, прогулки и возможного сна; не рассчитывай, что ребёнок долго займёт себя сам. Если возраст и режим неизвестны, не выдумывай их — предложи общий гибкий план для мамы. Время — ориентир: разрешай переносить дела, менять порядок и сокращать список. Отдых важнее списка задач; не обещай успеть всё и не вызывай чувство вины. Если действительно нужно уточнение, задай один короткий вопрос. Не используй фразу «пока все домашние ещё раскачиваются» и не предполагай наличие других членов семьи. Не добавляй автоматическую рекламу Greenway. Выведи подробный план дня целиком, не дели его на краткое вступление и скрытые подробности.",
        "menu_support": "Мне сейчас тяжело, устала от быта и детей. Поддержи меня тепло, как подруга.",
    }
    banners_map = {
        "menu_food": BANNER_FOOD,
        "menu_plan": BANNER_PLAN,
        "menu_support": BANNER_SUPPORT,
    }

    selected_prompt = prompts_map.get(callback.data, "")
    if selected_prompt:
        banner_ids = banners_map.get(callback.data)
        if callback.data == "menu_food" and FOOD_BANNERS:
            global food_banner_index
            # Передаём все баннеры, начиная с очередного, чтобы при ошибке
            # одного Telegram file_id функция answer_with_banner попробовала остальные.
            banner_ids = (
                FOOD_BANNERS[food_banner_index:]
                + FOOD_BANNERS[:food_banner_index]
            )
            food_banner_index = (food_banner_index + 1) % len(FOOD_BANNERS)
        elif callback.data == "menu_support" and BANNER_SUPPORT:
            global support_banner_index
            # Последовательная ротация; при ошибке одного file_id механизм
            # answer_with_banner сможет попробовать следующие изображения.
            banner_ids = (
                BANNER_SUPPORT[support_banner_index:]
                + BANNER_SUPPORT[:support_banner_index]
            )
            support_banner_index = (support_banner_index + 1) % len(BANNER_SUPPORT)

        await replace_callback_message(callback)
        if callback.data == "menu_plan":
            await start_plan_flow(callback.message, request_user_id=callback.from_user.id)
        else:
            await answer_with_gemini(
                callback.message,
                selected_prompt,
                banner_ids=banner_ids,
            )

def chaos_keyboard(session_id: int, stage: str) -> InlineKeyboardMarkup:
    if stage == "zone":
        rows = [
            [InlineKeyboardButton(text="🍽 Кухня", callback_data=f"cln:{session_id}:zone:kitchen")],
            [InlineKeyboardButton(text="🧸 Игрушки и детская", callback_data=f"cln:{session_id}:zone:kids")],
            [InlineKeyboardButton(text="👚 Одежда и вещи", callback_data=f"cln:{session_id}:zone:clothes")],
            [InlineKeyboardButton(text="🛋 Гостиная", callback_data=f"cln:{session_id}:zone:living")],
            [InlineKeyboardButton(text="🌪 Понемногу везде", callback_data=f"cln:{session_id}:zone:everywhere")],
        ]
    elif stage == "duration":
        rows = [[
            InlineKeyboardButton(text=f"⏱ {minutes} минут", callback_data=f"cln:{session_id}:time:{minutes}")
            for minutes in CHAOS_DURATIONS
        ]]
    else:
        rows = [[
            InlineKeyboardButton(text="🪫 Низкий", callback_data=f"cln:{session_id}:energy:low"),
            InlineKeyboardButton(text="🌿 Обычный", callback_data=f"cln:{session_id}:energy:normal"),
            InlineKeyboardButton(text="⚡️ Высокий", callback_data=f"cln:{session_id}:energy:high"),
        ]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def chaos_step_keyboard(session_id: int, step_number: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➡️ Следующая комната", callback_data=f"cln:{session_id}:next_room:{step_number}")],
            [InlineKeyboardButton(text="🔄 Ещё немного здесь", callback_data=f"cln:{session_id}:more:{step_number}")],
            [InlineKeyboardButton(text="☕ На сегодня хватит", callback_data=f"cln:{session_id}:stop:{step_number}")],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data=f"cln:{session_id}:home:{step_number}")],
        ]
    )


def chaos_next_zone_keyboard(session_id: int, current_zone: str) -> InlineKeyboardMarkup:
    zone_labels = {
        "kitchen": "🍽 Кухня",
        "kids": "🧸 Игрушки и детская",
        "clothes": "👚 Одежда и вещи",
        "living": "🛋 Гостиная",
        "everywhere": "🌪 Понемногу везде",
    }
    rows = [
        [InlineKeyboardButton(
            text=zone_labels[zone],
            callback_data=f"cln:{session_id}:nextzone:{zone}",
        )]
        for zone in CHAOS_ZONES
        if zone != current_zone
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def chaos_zone_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🍳 Кухня", callback_data="chaos:kitchen"),
                InlineKeyboardButton(text="🧸 Детская и игрушки", callback_data="chaos:kids"),
            ],
            [
                InlineKeyboardButton(text="🪞 Гостиная и зеркала", callback_data="chaos:living"),
                InlineKeyboardButton(text="🛁 Ванная комната", callback_data="chaos:bath"),
            ],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")],
        ]
    )


def chaos_zone_keyboard(zone: str) -> InlineKeyboardMarkup:
    rows = []
    product_callback = {
        "kitchen": "chaos:product:kitchen",
        "living": "chaos:product:glass",
        "bath": "chaos:product:bath",
    }.get(zone)
    product_label = {
        "kitchen": "✨ Как отмыть за 2 минуты без химии",
        "living": "🌿 Секрет идеальных зеркал",
        "bath": "🫧 Как убрать налёт без хлора",
    }.get(zone)
    if product_callback and product_label:
        rows.append([InlineKeyboardButton(text=product_label, callback_data=product_callback)])
    rows.extend([
        [InlineKeyboardButton(text="➡️ Другая комната", callback_data="chaos:menu")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def chaos_product_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✈️ Эко-чат в Telegram", url="https://t.me/+_fdqM43aOoA1ZjBi")],
            [InlineKeyboardButton(text="💬 Эко-чат в Max", url="https://max.ru/join/d5b4FKWGwFSNCYwEbX02Totc0c-8y8AIgzbz6xf-4Jo")],
            [InlineKeyboardButton(text="🔙 Вернуться к комнатам", callback_data="chaos:menu")],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")],
        ]
    )


CHAOS_ZONE_CARDS = {
    "kitchen": (
        "Фокус на 3 минуты: Остров чистоты 🍳\n\n"
        "Забудь про всю кухню. Освободи и протри ровно ОДНО место — раковину или варочную панель. "
        "Когда блестит этот центр, вся кухня сразу кажется опрятной!\n\n"
        "💡 Мамский чит-код:\n"
        "Чтобы не тереть пригоревший жир и нагар по 20 минут в резиновых перчатках "
        "(и не дышать химией рядом с детьми) — используй пасту Mystik и диск Инволвер. "
        "Смачиваешь водой, проводишь пару раз — и всё скрипит от чистоты за 2 минуты ✨"
    ),
    "living": (
        "Фокус на 3 минуты: Визуальный воздух 🪞\n\n"
        "Секрет свежей гостиной — убрать отпечатки пальцев с зеркал и взбить/поправить подушки на диване. "
        "Комната мгновенно преображается!\n\n"
        "💡 Мамский чит-код:\n"
        "Забудь про синие спреи с резким запахом и разводы от бумажных полотенец. "
        "Салфетка для стекла + обычная вода: протёрла один раз — и зеркало сияет без единого развода "
        "само за 30 секунд 🌿"
    ),
    "kids": (
        "Фокус на 3 минуты: Метод одного ящика 🧸\n\n"
        "Не пытайся сортировать лего от машинок и кукол, это сизифов труд. "
        "Возьми одну большую корзину или таз и просто сгреби в неё ВСЁ с пола за 120 секунд.\n\n"
        "Пол освободился — в комнате снова можно дышать и не бояться наступить на детальку! 🧘‍♀️"
    ),
    "bath": (
        "Фокус на 3 минуты: Блеск за минуту 🛁\n\n"
        "Смахни капли и белый налёт со смесителя и раковины. Чистый кран даёт эффект только что вымытой ванной!\n\n"
        "💡 Мамский чит-код:\n"
        "Салфетка в рубчик или замшевая для оптики/поверхностей забирает весь известковый налёт и "
        "мыльные разводы за одно движение влажной тканью. Никакой хлорки и едких гелей 🫧"
    ),
}


CHAOS_PRODUCT_CARD = (
    "Магия простой воды и микроволокна 🌿\n\n"
    "Вся эта фишка — японское микроволокно и паста Mystik от Greenway. Работают вообще без едких "
    "спреев и перчаток: намочила водой, прошлась — и всё скрипит. Для дома, где ползают малыши и "
    "вечно не хватает времени, это просто спасение.\n\n"
    "Я сама мама и веду уютные клиентские чаты, где делюсь быстрыми видео до/после, полезными "
    "эко-находками и собираю заказы для своих.\n\n"
    "Выбирай, где тебе удобнее заглянуть в гости 🤍☕️"
)


async def start_chaos_flow(message: Message) -> None:
    await message.answer(
        "В доме с детьми идеальный порядок живёт ровно 5 минут — и это нормально! 🙈\n\n"
        "Не надо генералить всю квартиру. Выбери одну зону, и мы наведём в ней визуальный уют "
        "всего за 3–5 минут без надрыва ✨",
        reply_markup=chaos_zone_menu_keyboard(),
    )


@dispatcher.callback_query(F.data.startswith("chaos:"))
async def process_chaos_zone_action(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None or not callback.data:
        return

    data = callback.data
    await replace_callback_message(callback)

    if data == "chaos:menu":
        await start_chaos_flow(callback.message)
        return

    if data.startswith("chaos:product:"):
        await callback.message.answer(
            CHAOS_PRODUCT_CARD,
            reply_markup=chaos_product_keyboard(),
        )
        return

    zone = data.split(":", 1)[1]
    card = CHAOS_ZONE_CARDS.get(zone)
    if card is None:
        return

    await callback.message.answer(
        card,
        reply_markup=chaos_zone_keyboard(zone),
    )


async def finish_chaos_flow(user_id: int, message: Message, session_id: int, timed_out: bool = False) -> None:
    session = chaos_sessions.get(user_id)
    if not session or session.get("id") != session_id or not session.get("active"):
        return
    session["active"] = False
    timer_task = session.get("timer_task")
    if timer_task and timer_task is not asyncio.current_task():
        timer_task.cancel()
    last_message = session.get("last_message")
    if last_message is not None:
        try:
            await last_message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    chaos_sessions.pop(user_id, None)
    if timed_out:
        ending = "⏰ Время вышло — и этого достаточно! Ты уделила дому столько времени, сколько планировала. Остальное подождёт 💛"
    else:
        ending = "🌷 На сегодня достаточно. Даже один маленький шаг — уже вклад в уют. Не нужно доделывать всё сразу; теперь можно выдохнуть 💛"
    await message.answer(ending, reply_markup=MENU_KEYBOARD)


async def chaos_timer(user_id: int, session_id: int, duration: int, message: Message) -> None:
    try:
        await asyncio.sleep(duration * 60)
        await finish_chaos_flow(user_id, message, session_id, timed_out=True)
    except asyncio.CancelledError:
        return


def chaos_seconds_left(session: dict) -> int:
    started_at = session.get("started_at")
    duration = session.get("duration")
    if started_at is None or duration is None:
        return duration * 60 if duration else 0
    return max(0, int(duration * 60 - (time.monotonic() - started_at)))


def chaos_target_steps(session: dict, sequence: list) -> int:
    """Количество действий зависит от времени и энергии."""
    duration = session.get("duration", 5)
    target = {5: 4, 10: 6, 15: 8}.get(duration, 4)
    if session.get("energy") == "low":
        target = max(2, target - 2)
    elif session.get("energy") == "high":
        target = min(len(sequence), target + 1)
    return min(len(sequence), target)


async def generate_chaos_step(message: Message, user_id: int, session_id: int, alternate: bool = False) -> None:
    session = chaos_sessions.get(user_id)
    if not session or session.get("id") != session_id or not session.get("active"):
        return
    if chaos_seconds_left(session) <= 0:
        await finish_chaos_flow(user_id, message, session_id, timed_out=True)
        return

    zone = session.get("zone", "everywhere")
    sequence = CHAOS_STEP_SEQUENCES.get(zone, CHAOS_STEP_SEQUENCES["everywhere"])
    used_by_zone = session.setdefault("used_tasks", {}).setdefault(zone, [])
    available = [task for task in sequence if task not in used_by_zone]
    if not available:
        # Start a fresh cycle only after every task in this zone was shown once.
        used_by_zone.clear()
        available = list(sequence)
    target_steps = min(chaos_target_steps(session, sequence), len(available))
    remaining = chaos_seconds_left(session)
    if remaining <= 0:
        await finish_chaos_flow(user_id, message, session_id, timed_out=True)
        return

    session["busy"] = True
    session["step_number"] += 1
    step_number = session["step_number"]
    count = target_steps
    if remaining < 120:
        count = min(count, 2 if session.get("energy") == "low" else 3)
    tasks = available[:count]
    used_by_zone.extend(tasks)
    session["last_tasks"] = tasks
    session["stage"] = "steps"
    title = f"🧹 <b>{CHAOS_ZONES.get(zone, 'дом')}</b> — твой мини-план"
    task_lines = [f"{index}. {task}" for index, task in enumerate(tasks, start=1)]
    if session.get("energy") == "low":
        intro = "Выбирай только то, на что сейчас хватает сил. Можно остановиться после любого пункта 💛"
    else:
        intro = "Делай по порядку или выбирай любой пункт — без гонки 🌿"
    if remaining < 60:
        intro += "\n\n⏳ Времени осталось совсем немного — сделай один небольшой шаг или просто выдохни."
    text = title + "\n\n" + intro + "\n\n" + "\n".join(task_lines)
    try:
        await replace_last_chaos_message(session)
        sent = await message.answer(
            text,
            reply_markup=chaos_step_keyboard(session_id, step_number),
            parse_mode=ParseMode.HTML,
        )
        session["last_message"] = sent
    except Exception:
        logger.exception("Could not send cleanup task list")
    finally:
        current = chaos_sessions.get(user_id)
        if current and current.get("id") == session_id:
            current["busy"] = False


async def replace_last_chaos_message(session: dict) -> None:
    last_message = session.get("last_message")
    if last_message is not None:
        try:
            await last_message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


def chaos_zone_complete_keyboard(session_id: int, step_number: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➡️ Следующая комната", callback_data=f"cln:{session_id}:next_room:{step_number}")],
            [InlineKeyboardButton(text="🛑 На сегодня хватит", callback_data=f"cln:{session_id}:stop:{step_number}")],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data=f"cln:{session_id}:home:{step_number}")],
        ]
    )


@dispatcher.callback_query(F.data.startswith("cln:"))
async def process_chaos_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None or not callback.data:
        return
    parts = callback.data.split(":")
    if len(parts) < 3:
        return
    try:
        session_id = int(parts[1])
    except ValueError:
        return
    action = parts[2]
    message = callback.message
    user_id = callback.from_user.id
    session = chaos_sessions.get(user_id)
    if not session or session.get("id") != session_id or not session.get("active"):
        await message.answer("Эта кнопка уже устарела 🌿 Если захочешь начать заново, выбери «🧹 Разгрести хаос» в меню.")
        return
    if session.get("busy"):
        return

    if action == "zone" and len(parts) == 4 and parts[3] in CHAOS_ZONES:
        if session.get("stage") != "zone":
            return
        session["zone"] = parts[3]
        session["stage"] = "duration"
        await replace_callback_message(callback)
        await message.answer("Сколько времени выделим на себя и дом?", reply_markup=chaos_keyboard(session_id, "duration"))
        return

    if action == "time" and len(parts) == 4 and parts[3].isdigit():
        duration = int(parts[3])
        if duration not in CHAOS_DURATIONS or session.get("stage") != "duration":
            return
        session["duration"] = duration
        session["started_at"] = time.monotonic()
        session["stage"] = "energy"
        session["timer_task"] = asyncio.create_task(chaos_timer(user_id, session_id, duration, message))
        await replace_callback_message(callback)
        await message.answer("Сколько у тебя сейчас сил?", reply_markup=chaos_keyboard(session_id, "energy"))
        return

    if action == "energy" and len(parts) == 4 and parts[3] in CHAOS_ENERGIES:
        if session.get("stage") != "energy":
            return
        session["energy"] = parts[3]
        session["stage"] = "steps"
        await replace_callback_message(callback)
        await generate_chaos_step(message, user_id, session_id)
        return

    if action == "nextzone" and len(parts) == 4 and parts[3] in CHAOS_ZONES:
        if session.get("stage") != "next_zone" or parts[3] == session.get("zone"):
            return
        if chaos_seconds_left(session) <= 0:
            await finish_chaos_flow(user_id, message, session_id, timed_out=True)
            return
        session["zone"] = parts[3]
        session["step_index"] = 0
        session["stage"] = "steps"
        await replace_callback_message(callback)
        await generate_chaos_step(message, user_id, session_id)
        return

    if action in {"next_room", "more", "stop", "home"}:
        if session.get("stage") not in {"steps", "zone_complete"} or len(parts) != 4:
            return
        try:
            clicked_step = int(parts[3])
        except ValueError:
            return
        if clicked_step != session.get("step_number"):
            await message.answer("Этот шаг уже сменился 🌿 Посмотри на последнее сообщение с актуальными кнопками.")
            return
        if chaos_seconds_left(session) <= 0:
            await finish_chaos_flow(user_id, message, session_id, timed_out=True)
            return
        if action == "stop":
            await replace_callback_message(callback)
            await finish_chaos_flow(user_id, message, session_id)
            return
        if action == "home":
            await replace_callback_message(callback)
            await finish_chaos_flow(user_id, message, session_id)
            return
        if action == "next_room":
            await replace_callback_message(callback)
            session["stage"] = "next_zone"
            zone_message = await message.answer(
                "Куда отправимся дальше? Выбери другую зону — время и силы сохраняются 🌿",
                reply_markup=chaos_next_zone_keyboard(session_id, session["zone"]),
            )
            session["last_message"] = zone_message
            return


@dispatcher.callback_query(F.data.startswith("support:") | (F.data == "menu:main"))
async def process_support_action(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    data = callback.data or ""
    user_id = callback.from_user.id
    if data in {"support:home", "menu:main"}:
        support_sessions.pop(user_id, None)
        await replace_callback_message(callback)
        await callback.message.answer(
            "🏠 Главное меню. Выбирай, чем помочь:",
            reply_markup=MENU_KEYBOARD,
        )
        return
    if data == "support:choose_again":
        # Не завершаем текущий сценарий, пока мама явно не выберет другой.
        await replace_callback_message(callback)
        await callback.message.answer(
            "Какой поддержки тебе хочется сейчас? 💛",
            reply_markup=support_choice_keyboard(),
        )
        return
    parts = data.split(":")
    if len(parts) != 3 or parts[1] != "choose" or parts[2] not in SUPPORT_SCENARIOS:
        return
    key = parts[2]
    await replace_callback_message(callback)
    greeting_text = SUPPORT_SCENARIOS[key]["greeting"]
    async with get_user_request_lock(user_id):
        support_sessions[user_id] = key
        conversation_history_by_user.pop(user_id, None)
        await callback.message.answer(
            greeting_text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💛 Выбрать другой вариант", callback_data="support:choose_again")],
                    [InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:main")],
                ]
            ),
        )
        append_history(user_id, None, greeting_text)


@dispatcher.callback_query(F.data == "back_to_menu")
async def process_back_to_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    message = callback.message
    await replace_callback_message(callback)
    await answer_with_banner(
        message,
        START_CAPTION,
        BANNER_START,
        reply_markup=inline_kb,
        parse_mode=ParseMode.HTML,
    )


def personalized_system_prompt(
    user_name: str | None,
    support_mode: bool = False,
    scenario_instruction: str | None = None,
) -> str:
    # Не используем латинское имя в русскоязычном общении: лучше «дорогая».
    usable_name = user_name if user_name and re.fullmatch(r"[А-Яа-яЁё-]+", user_name) else None
    user_greeting = (
        f"6. Собеседницу зовут {usable_name}. Если обращаешься по имени, используй ТОЛЬКО это имя без изменения формы: не придумывай уменьшительные, ласкательные или искажённые варианты (например, из «Анна» нельзя делать «Аннешка»). Если имя звучит неестественно в обращении, просто скажи «дорогая» или ответь без имени. Не ставь обращение в каждое сообщение.\n"
        if usable_name
        else "6. Обращайся к собеседнице тепло и по-доброму (милая, дорогая). Если имя записано латиницей, не произноси его в русскоязычном ответе.\n"
    )

    if support_mode:
        selected_scenario = scenario_instruction or "Следуй выбранному сценарию поддержки."
        support_addressing = (
            "Не используй обращения «милая», «дорогая» и имя как привычную заставку. "
            "Обращайся по имени только изредка и если это звучит естественно; чаще отвечай сразу по существу."
        )
        warm_critical_rule = (
            "\n\nКРИТИЧЕСКОЕ ПРАВИЛО ДЛЯ СЦЕНАРИЯ WARM:\n"
            "- ЗАПРЕЩЕНО писать «выговорись», «расскажи подробнее», «я слушаю» и задавать вопросы о проблеме.\n"
            "- ЗАПРЕЩЕНЫ абстрактные книжные фразы («остаться одной со своими чувствами», «звенящая пустота»).\n"
            "- Отвечай как близкая живая подруга:\n"
            "  1) Встань на сторону мамы: раздели обиду/боль простыми словами («Это жесть», «Как же я тебя понимаю», «Хочется забиться в угол»).\n"
            "  2) Дай безоговорочную поддержку и любовь — обними словами.\n"
            "  3) Дай 1 простое действие на заземление прямо сейчас (запереться в ванной на 10 минут, включить воду, заварить чай, завернуться в плед, выпить воды).\n"
            "Это правило важнее общих правил стиля. Не заканчивай вопросом."
            if scenario_instruction and scenario_instruction.lstrip().startswith("🤍 Тёплые слова")
            else ""
        )
        return f"{SUPPORT_STYLE}\n\nТЕКУЩИЙ СЦЕНАРИЙ:\n{selected_scenario}{warm_critical_rule}\n\n{support_addressing}"

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
    support_mode: bool = False,
    scenario_instruction: str | None = None,
) -> str:
    # Повторные попытки выполняются в answer_with_gemini, поэтому здесь
    # не создаём ещё один вложенный цикл, который надолго задерживает ответ.
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=personalized_system_prompt(
                user_name,
                support_mode=support_mode,
                scenario_instruction=scenario_instruction,
            ),
        ),
    )
    return (response.text or "").strip()


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


async def send_final_response(
    message: Message,
    reply: str,
    banner_ids: list[str] | tuple[str, ...] | None = None,
    food_followup: bool = False,
    ignore_split: bool = False,
    plan_flow: bool = False,
    support_mode: bool = False,
) -> None:
    # Рекламная автоссылка не должна попадать в эмоциональную поддержку.
    shop_url = "https://greenwayglobal.com/shop?gw=etJ4vRkF8D"
    product_names = ("mystik", "инволвер", "green fiber", "biotrim", "биотрим")
    reply_lower = reply.lower()
    if not support_mode and any(name in reply_lower for name in product_names) and shop_url not in reply:
        reply = reply.rstrip() + (
            "\\n\\n🌿 Посмотреть эти средства можно в "
            f"[официальном эко-магазине]({shop_url})."
        )
    # Разделитель принимается и в укороченном виде, но не показывается в Telegram.
    parts = [
        p.strip()
        for p in re.split(r"(?im)^\s*===SPLIT(?:===)?\s*$", reply)
        if p.strip()
    ]
    if ignore_split:
        parts = ["\n\n".join(parts)] if parts else [re.sub(r"===SPLIT(?:===)?", "", reply).strip()]
    is_food_response = food_followup or (
        bool(banner_ids) and any(item in FOOD_BANNERS for item in banner_ids)
    )
    has_banner = choose_banner(banner_ids) is not None

    if plan_flow:
        # В плане поддерживаем прежнюю схему: до раскрытия текст остаётся
        # во временном хранилище и выдаётся только по кнопке.
        details_text = "\n\n".join(parts).strip() if parts else re.sub(r"===SPLIT(?:===)?", "", reply).strip()
        pending_details[message.chat.id] = details_text
        pending_details_food.discard(message.chat.id)
        intro = (
            "📋 <b>День по полочкам</b> 🌿\n\n"
            "Соберём мягкий, гибкий план для тебя: забота о детях, важные дела и "
            "немного времени на себя. Это ориентир, а не расписание, которому нужно "
            "обязательно соответствовать 💛"
        )
        expand_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📖 Развернуть подробнее", callback_data="expand_details")],
                [InlineKeyboardButton(text="✏️ Изменить возраст детей", callback_data="family_age:edit")],
            ]
        )
        plan_banner = await get_next_plan_banner()
        if plan_banner:
            await answer_with_banner(
                message, intro, [plan_banner],
                reply_markup=expand_keyboard, parse_mode=ParseMode.HTML,
            )
        else:
            await message.answer(
                intro, reply_markup=expand_keyboard, parse_mode=ParseMode.HTML,
            )
        return
    # При баннере держим первую подпись в пределах лимита Telegram для caption.
    chunk_limit = 900 if has_banner else TELEGRAM_CHUNK_SIZE
    another_food_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🥣 Ещё вариант", callback_data="another_food")]
        ]
    )

    if len(parts) <= 1:
        display_reply = re.sub(r"===SPLIT(?:===)?", "", parts[0] if parts else reply).strip()
        chunks = split_response(display_reply, limit=chunk_limit)
        for idx, chunk in enumerate(chunks):
            is_last = idx == len(chunks) - 1
            formatted = format_telegram_html(chunk)
            markup = (
                another_food_keyboard if is_last and is_food_response
                else support_return_keyboard() if is_last and support_mode
                else MENU_KEYBOARD if is_last else None
            )
            if idx == 0 and banner_ids is not None:
                await answer_with_banner(
                    message, formatted, banner_ids,
                    reply_markup=markup, parse_mode=ParseMode.HTML,
                )
            else:
                await message.answer(
                    formatted,
                    reply_markup=markup,
                    parse_mode=ParseMode.HTML,
                )
        return

    intro_text = re.sub(r"===SPLIT(?:===)?", "", parts[0]).strip()
    details_text = re.sub(r"===SPLIT(?:===)?", "", "\n\n".join(parts[1:])).strip()
    expand_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📖 Развернуть подробнее", callback_data="expand_details")]
        ]
    )
    pending_details[message.chat.id] = details_text
    if is_food_response:
        pending_details_food.add(message.chat.id)
    else:
        pending_details_food.discard(message.chat.id)

    intro_chunks = split_response(intro_text, limit=chunk_limit)
    for idx, chunk in enumerate(intro_chunks):
        is_last = idx == len(intro_chunks) - 1
        markup = expand_keyboard if is_last else None
        formatted = format_telegram_html(chunk)
        if idx == 0 and banner_ids is not None:
            await answer_with_banner(
                message, formatted, banner_ids,
                reply_markup=markup, parse_mode=ParseMode.HTML,
            )
        else:
            await message.answer(
                formatted,
                reply_markup=markup,
                parse_mode=ParseMode.HTML,
            )

@dispatcher.callback_query(lambda c: c.data == "another_food")
async def process_another_food(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return

    # Убираем нажатую кнопку, чтобы не запускать запрос повторно.
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # Запрашиваем только новый рецепт, без повторного приветствия и вступления.
    prompt = (
        "Предложи ТОЛЬКО новый рецепт для всей семьи, отличный от последнего. "
        "Не начинай с приветствия, знакомства или описания бота и не повторяй "
        "стартовое сообщение. Сразу укажи название блюда, ингредиенты и короткие "
        "шаги приготовления. Каждый шаг приготовления обязательно выведи с новой "
        "строки и с нумерацией строго в формате «1. ...», «2. ...», «3. ...». "
        "Не используй ненумерованный список вместо шагов. Используй обычные "
        "недорогие продукты и минимум активного времени у плиты (желательно 15–30 "
        "минут). Не повторяй недавние блюда. В конце спроси, какие продукты уже есть дома."
    )
    await answer_with_gemini(
        callback.message,
        prompt,
        request_user_id=callback.from_user.id,
        food_followup=True,
        ignore_split=True,
    )


@dispatcher.callback_query(lambda c: c.data == "expand_details")
async def process_expand_details(callback: CallbackQuery) -> None:
    chat_id = callback.message.chat.id
    details = pending_details.pop(chat_id, None)
    is_food_details = chat_id in pending_details_food
    pending_details_food.discard(chat_id)

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
            reply_markup=(
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🥣 Ещё вариант", callback_data="another_food")]
                    ]
                )
                if is_last and is_food_details
                else MENU_KEYBOARD if is_last else None
            ),
            parse_mode=ParseMode.HTML,
        )

async def answer_with_gemini(
    message: Message,
    prompt: str | None = None,
    voice_file_id: str | None = None,
    banner_ids: list[str] | tuple[str, ...] | None = None,
    request_user_id: int | None = None,
    food_followup: bool = False,
    ignore_split: bool = False,
    plan_flow: bool = False,
    support_mode: bool = False,
    support_scenario_key: str | None = None,
    record_user_content: bool = True,
) -> None:
    user_id = request_user_id or (message.from_user.id if message.from_user else message.chat.id)
    if prompt is None and voice_file_id is None:
        return
    # В поддержке ответ должен оставаться цельным, без скрываемой второй части.
    if support_mode:
        ignore_split = True

    async with get_user_request_lock(user_id):
        if support_scenario_key is not None:
            if support_scenario_key not in SUPPORT_SCENARIOS:
                return
            # Дождались завершения предыдущего запроса пользователя: старый ответ
            # не сможет дописать историю уже после переключения сценария.
            conversation_history_by_user.pop(user_id, None)
            support_sessions[user_id] = support_scenario_key
            support_mode = True
            ignore_split = True
        elif support_mode and support_sessions.get(user_id) not in SUPPORT_SCENARIOS:
            await message.answer(
                "Выбери, какая поддержка тебе сейчас нужна.",
                reply_markup=support_choice_keyboard(),
            )
            return

        temporary_message = await send_thinking_message(message)
        try:
            if voice_file_id is not None:
                audio_bytes = await download_voice_audio(voice_file_id)
                user_content = voice_user_content(audio_bytes)
            else:
                user_content = text_user_content(prompt or "")

            history = conversation_history_by_user.get(user_id, [])
            scenario_instruction = None
            if support_mode:
                scenario = SUPPORT_SCENARIOS.get(support_sessions.get(user_id, ""), {})
                scenario_instruction = (
                    scenario.get("label", "")
                    + "\n"
                    + scenario.get("instruction", "")
                    + "\n\nПродолжай естественный разговор с учётом истории текущего сценария. "
                    "Отвечай на последнюю реплику, включая новые подробности; не повторяй стартовый ответ. "
                    "Не используй общий совет вместо реакции на конкретную ситуацию. "
                    "Если пользователь просит только выслушать — не советуй. Не рекламируй товары."
                )
            request_contents = [*history, user_content]
            reply = None

            for attempt in range(2):
                try:
                    reply = await asyncio.to_thread(
                        generate_reply,
                        request_contents,
                        user_names.get(user_id),
                        support_mode,
                        scenario_instruction,
                    )
                    if reply:
                        break
                except Exception as error:
                    logger.warning("Attempt %s failed: %s", attempt + 1, error)
                    if attempt == 0:
                        await asyncio.sleep(2)
                    else:
                        if support_mode:
                            error_message = (
                                "Не получилось получить ответ сейчас. Предыдущие сообщения сохранились; "
                                "отправь последнюю реплику ещё раз, и продолжим с неё."
                            )
                            error_markup = None
                        else:
                            error_message = (
                                "Немножко подвисла связь у серверов 🙈\n\n"
                                "Сделай пока глоток вкусного чая или кофе ☕️🍪\n"
                                "Загляни через 15–20 минут — всё как раз наладится, "
                                "и я буду на связи! 🌸✨"
                            )
                            error_markup = MENU_KEYBOARD
                        await message.answer(error_message, reply_markup=error_markup)
                        return

            if not reply:
                if support_mode:
                    await message.answer(
                        "Не получилось сформировать ответ на этот раз. Предыдущие сообщения сохранились; "
                        "отправь последнюю реплику ещё раз, и продолжим с неё."
                    )
                else:
                    await message.answer(
                        "Ой, милая, отвлеклась на секунду! Нажми ещё раз на кнопочку меню 🌸",
                        reply_markup=MENU_KEYBOARD,
                    )
                return

            if not support_mode:
                append_history(user_id, user_content, reply)
            await send_final_response(
                message,
                reply,
                banner_ids=banner_ids,
                food_followup=food_followup,
                ignore_split=ignore_split,
                plan_flow=plan_flow,
                support_mode=support_mode,
            )
            if support_mode:
                # Сохраняем ответ поддержки только после успешной отправки в Telegram.
                append_history(
                    user_id,
                    user_content if record_user_content else None,
                    reply,
                )
        except Exception as general_error:
            logger.exception(
                "General error in answer_with_gemini: %s",
                general_error,
            )
            if support_mode:
                await message.answer(
                    "Не получилось обработать сообщение сейчас. Предыдущие сообщения сохранились; "
                    "отправь последнюю реплику ещё раз, и продолжим с неё."
                )
            else:
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

    user_id = message.from_user.id if message.from_user else message.chat.id
    await answer_with_gemini(
        message,
        voice_file_id=message.voice.file_id,
        support_mode=bool(support_sessions.get(user_id)),
    )


@dispatcher.message(Command("food"))
async def handle_food_command(message: Message) -> None:
    global food_banner_index
    banner_ids = FOOD_BANNERS[food_banner_index:] + FOOD_BANNERS[:food_banner_index]
    food_banner_index = (food_banner_index + 1) % len(FOOD_BANNERS)
    await answer_with_gemini(message, MENU_BUTTONS[0], banner_ids=banner_ids)


@dispatcher.message(Command("chaos"))
async def handle_chaos_command(message: Message) -> None:
    await start_chaos_flow(message)


async def get_next_plan_banner() -> str | None:
    """Возвращает следующее фото по порядку в течение текущего запуска бота."""
    global plan_banner_index
    if not BANNER_PLAN:
        return None
    photo = BANNER_PLAN[plan_banner_index % len(BANNER_PLAN)]
    plan_banner_index = (plan_banner_index + 1) % len(BANNER_PLAN)
    return photo


async def start_plan_flow(
    message: Message,
    request_user_id: int | None = None,
    force_generic: bool = False,
) -> None:
    user_id = request_user_id or (
        message.from_user.id if message.from_user else message.chat.id
    )
    ages: list[dict] = []
    if not force_generic:
        try:
            ages = await asyncio.to_thread(load_family_ages, user_id)
        except FamilyProfileUnavailable:
            logger.warning("Family profile unavailable (%s)", user_id)
            await message.answer(
                "Пока не удаётся получить постоянный профиль семьи, поэтому составлю общий план. "
                "Возраст не будет сохранён.",
                reply_markup=MENU_KEYBOARD,
            )
            force_generic = True

    if not force_generic and not ages:
        await start_family_age_collection(message, user_id, had_existing_profile=False)
        return

    age_context = ""
    if ages:
        age_context = (
            "\n\nИзвестные сведения профиля семьи (возраст детей по порядку от старшего к младшему):\n"
            + family_age_summary(ages)
            + "\nУчитывай только эти возраста. Не делай выводов о школе, садике, режиме, сне "
            "или занятиях, если мама отдельно этого не сообщала."
        )

    await answer_with_gemini(
        message,
        "Составь тёплый и гибкий план именно для мамы: блоки заботы о детях, домашних дел и отдыха. "
        "Учитывай только известный контекст о возрасте детей, режиме, школе, садике и занятиях. "
        "Если известен младенец или малыш, оставь гибкие окна для заботы о нём; не рассчитывай, "
        "что ребёнок долго займёт себя сам. Если возраст и режим неизвестны, не выдумывай их — "
        "предложи общий гибкий план для мамы. Время — ориентир: разрешай переносить дела, менять "
        "порядок и сокращать список. Отдых важнее списка задач; не обещай успеть всё и не вызывай "
        "чувство вины. Если действительно нужно уточнение, задай один короткий вопрос. Не используй "
        "фразу «пока все домашние ещё раскачиваются» и не предполагай наличие других членов семьи. "
        "Не добавляй автоматическую рекламу Greenway. Выведи подробный план дня целиком, без вводного "
        "приветствия, чтобы он открылся отдельным сообщением после нажатия кнопки."
        + age_context,
        ignore_split=True,
        plan_flow=True,
        request_user_id=user_id,
    )


@dispatcher.callback_query(F.data == "family_age:skip")
async def skip_family_age(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    user_id = callback.from_user.id
    pending_family_profile.pop(user_id, None)
    await start_plan_flow(callback.message, request_user_id=user_id, force_generic=True)


@dispatcher.callback_query(F.data == "family_age:edit")
async def edit_family_age(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    user_id = callback.from_user.id
    try:
        existing_ages = await asyncio.to_thread(load_family_ages, user_id)
    except FamilyProfileUnavailable:
        logger.warning("Family profile unavailable during edit (%s)", user_id)
        await callback.message.answer(
            "Сейчас не получается открыть профиль. Попробуй немного позже.",
            reply_markup=MENU_KEYBOARD,
        )
        return
    await start_family_age_collection(
        callback.message,
        user_id,
        had_existing_profile=bool(existing_ages),
    )


@dispatcher.callback_query(F.data == "family_age:save")
async def save_family_age(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    user_id = callback.from_user.id
    state = pending_family_profile.get(user_id)
    if not state or state.get("stage") != "confirming":
        await callback.message.answer("Этот запрос уже завершён. Открой раздел «День по полочкам» ещё раз.")
        return
    ages = state.get("ages", [])
    try:
        await asyncio.to_thread(save_family_ages, user_id, ages)
    except FamilyProfileUnavailable:
        logger.warning("Family profile save failed (%s)", user_id)
        pending_family_profile.pop(user_id, None)
        await callback.message.answer(
            "Не удалось сохранить возраст в постоянный профиль. Ничего не сохранено; "
            "сейчас составлю общий план без этих сведений.",
            reply_markup=MENU_KEYBOARD,
        )
        await start_plan_flow(
            callback.message,
            request_user_id=user_id,
            force_generic=True,
        )
        return
    pending_family_profile.pop(user_id, None)
    await callback.message.answer("Готово, запомнила возраст детей. 🌿")
    await start_plan_flow(callback.message, request_user_id=user_id)


@dispatcher.callback_query(F.data == "family_age:cancel")
async def cancel_family_age(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    user_id = callback.from_user.id
    state = pending_family_profile.pop(user_id, None) or {}
    await start_plan_flow(
        callback.message,
        request_user_id=user_id,
        force_generic=not state.get("had_existing_profile", False),
    )


@dispatcher.message(Command("plan"))
async def handle_plan_command(message: Message) -> None:
    await start_plan_flow(message)


@dispatcher.message(Command("support"))
async def handle_support_command(message: Message) -> None:
    await start_support_flow(message)


@dispatcher.message(Command("reset_me"))
async def handle_reset_me(message: Message) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя; данные не изменены.")
        return

    user_id = message.from_user.id
    try:
        async with get_user_request_lock(user_id):
            # Delete the remote family profile first; if the configured database is
            # temporarily unavailable, do not claim that personal data was erased.
            await asyncio.to_thread(delete_family_profile, user_id)
            await asyncio.to_thread(delete_user_data_from_database, user_id)
            user_names.pop(user_id, None)
            conversation_history_by_user.pop(user_id, None)
            pending_family_profile.pop(user_id, None)
            support_sessions.pop(user_id, None)
            radiance_states.pop(user_id, None)
            pending_kids_age.discard(user_id)
            kids_generation_in_progress.discard(user_id)
    except Exception as error:
        logger.warning("Failed to reset user data (%s)", type(error).__name__)
        await message.answer(
            "Не удалось полностью очистить персональные данные. Ничего не подтверждаю как удалённое. "
            "Попробуй позже."
        )
        return

    await message.answer(
        "Готово — сохранённое имя, история диалога и профиль семьи удалены. "
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

    # Any reply-menu selection cancels an unfinished selfie state.
    if prompt in MENU_BUTTONS:
        radiance_states.pop(user_id, None)
        if prompt != MENU_BUTTONS[5]:
            pending_kids_age.discard(user_id)

    if user_id in pending_kids_age and prompt not in MENU_BUTTONS:
        parsed_ages = parse_child_ages(prompt)
        if not parsed_ages or len(parsed_ages) != 1:
            await message.answer(
                "Не совсем поняла возраст. Напиши один возраст, например «8 месяцев» или «2 года».",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ Отмена / Назад", callback_data="kids:cancel_age")],
                ]),
            )
            return
        try:
            await asyncio.to_thread(save_family_ages, user_id, parsed_ages)
        except FamilyProfileUnavailable:
            pending_kids_age.discard(user_id)
            await message.answer(
                "Не получилось сохранить возраст. Ничего не изменено — попробуй позже 🌿",
                reply_markup=MENU_KEYBOARD,
            )
            return
        pending_kids_age.discard(user_id)
        await message.answer("Спасибо, запомнила возраст в профиле семьи 🌿")
        await send_kids_activity(
            message,
            user_id,
            child_number=int(parsed_ages[0]["child_number"]),
        )
        return

    if prompt == MENU_BUTTONS[4]:
        await start_radiance_flow(message, user_id)
        return

    if prompt == MENU_BUTTONS[5]:
        await start_kids_flow(message, user_id)
        return

    profile_state = pending_family_profile.get(user_id)
    if profile_state:
        if profile_state.get("stage") == "collecting":
            parsed_ages = parse_child_ages(prompt)
            if not parsed_ages:
                await message.answer(
                    "Не совсем поняла возраст. Напиши по одному возрасту через запятую, "
                    "от старшего к младшему, например: 14 лет, 7 лет, 8 месяцев. "
                    "Или нажми «Без возраста»."
                )
                return
            profile_state["stage"] = "confirming"
            profile_state["ages"] = parsed_ages
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Да, запомнить", callback_data="family_age:save")],
                    [InlineKeyboardButton(text="↩️ Не сохранять", callback_data="family_age:cancel")],
                ]
            )
            await message.answer(
                "Вот что я собираюсь запомнить — от старшего ребёнка к младшему:\n\n"
                + family_age_summary(parsed_ages)
                + "\n\nСохранить эти сведения в профиле семьи?",
                reply_markup=keyboard,
            )
            return
        if profile_state.get("stage") == "confirming":
            await message.answer("Пожалуйста, выбери одну из кнопок: сохранить сведения или не сохранять.")
            return

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

    # Reply-кнопка поддержки может приходить с различающимися emoji-вариантами.
    # Сравниваем устойчивую текстовую часть, чтобы не отправлять её в Gemini как обычный запрос.
    normalized_prompt = re.sub(r"[^\w\s]", "", prompt).casefold()
    if (
        prompt == MENU_BUTTONS[3]
        or "тёплая поддержка" in normalized_prompt
        or "теплая поддержка" in normalized_prompt
    ):
        await start_support_flow(message, request_user_id=user_id)
        return

    # При переходе в другой раздел завершаем сценарий поддержки.
    if prompt in MENU_BUTTONS[:3]:
        support_sessions.pop(user_id, None)

    # Кнопки ReplyKeyboard приходят как обычный текст, не как callback.
    # Для рубрики еды важно явно передать список фотографий.
    menu_prompts = {
        MENU_BUTTONS[0]: (
            "Предложи разнообразное, простое и недорогое блюдо для всей семьи "
            "из обычных продуктов. Минимум активного времени у плиты, желательно "
            "15-30 минут. Не повторяй блюда из нашей предыдущей переписки. "
            "В конце спроси, какие продукты уже есть дома, чтобы подобрать "
            "рецепт из них."
        ),
        MENU_BUTTONS[2]: "Составь тёплый и гибкий план именно для мамы: блоки заботы о детях, домашних дел и отдыха. Учитывай только известный контекст о возрасте детей, режиме, школе, садике и занятиях. Если известен младенец или малыш, оставь гибкие окна для кормлений, прогулки и возможного сна; не рассчитывай, что ребёнок долго займёт себя сам. Если возраст и режим неизвестны, не выдумывай их — предложи общий гибкий план для мамы. Время — ориентир: разрешай переносить дела, менять порядок и сокращать список. Отдых важнее списка задач; не обещай успеть всё и не вызывай чувство вины. Если действительно нужно уточнение, задай один короткий вопрос. Не используй фразу «пока все домашние ещё раскачиваются» и не предполагай наличие других членов семьи. Не добавляй автоматическую рекламу Greenway. Выведи подробный план дня целиком, не дели его на краткое вступление и скрытые подробности.",
    }
    selected_prompt = menu_prompts.get(prompt, prompt)
    if prompt == MENU_BUTTONS[0]:
        global food_banner_index
        banner_ids = FOOD_BANNERS[food_banner_index:] + FOOD_BANNERS[:food_banner_index]
        food_banner_index = (food_banner_index + 1) % len(FOOD_BANNERS)
        await answer_with_gemini(message, selected_prompt, banner_ids=banner_ids)
        return

    if prompt == MENU_BUTTONS[1]:
        await start_chaos_flow(message)
        return

    if prompt == MENU_BUTTONS[2]:
        await start_plan_flow(message)
        return

    if support_sessions.get(user_id):
        await answer_with_gemini(message, prompt, support_mode=True)
        return

    await answer_with_gemini(message, selected_prompt)

async def main() -> None:
    logger.info("Starting Telegram bot with model %s", GEMINI_MODEL)
    initialize_user_state()
    _schedule_analytics_task(_backfill_sqlite_users_sync)
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
