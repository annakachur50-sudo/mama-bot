import asyncio
import html
import logging
import os
from aiohttp import web
import time

import random
import re
import sqlite3

import psycopg

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
        "label": "💬 Мне нужно выговориться",
        "instruction": "Если пользователь ещё не рассказал ситуацию, можно задать один простой открытый вопрос. После рассказа отреагируй на конкретные факты и смысл её слов простым языком, не добавляя предполагаемых чувств или обстоятельств. Не пересказывай длинно и не превращай разговор в допрос. Не советуй, не предлагай упражнений и не переходи к решениям без запроса. Если пользователь говорит, что хочет просто выговориться, подтверди это естественно и оставь ей пространство продолжить; не задавай обязательный вопрос в конце.",
    },
    "warm": {
        "label": "🤍 Мне нужны тёплые слова",
        "instruction": "Это сценарий именно тёплых слов, а не анализа проблемы. Сначала посмотри на историю диалога: если мама уже рассказывала, что происходит, поддержи её конкретно в этой ситуации и отзовись на важную деталь. Если контекста пока нет, всё равно дай полноценные тёплые слова — искренние, простые и не шаблонные, без выдуманных обстоятельств, чувств и заслуг. Не ограничивайся пересказом её выбора, фразами вроде «ты не одна» или «ты справляешься» и общими рассуждениями о материнстве. Не превращай первый ответ в уточняющий вопрос и не давай советов, пока их не попросили. Говори так, будто обращаешься к конкретному человеку, а не к любой маме.",
    },
    "advice": {
        "label": "🌿 Хочу бережный совет",
        "instruction": "Если пользователь просит совета, дай один-два конкретных, реалистичных следующих шага, привязанных к названной ситуации, а не только рассуждение о проблеме. Не приписывай ей страх потерять контроль, неумение делегировать или другие мотивы, которых она не называла. Если для полезного совета не хватает ключевой информации, задай один уместный уточняющий вопрос. Если она явно просит только выслушать и не хочет советов, не навязывай их.",
    },
    "pause": {
        "label": "☕ Хочу немного передохнуть",
        "instruction": "Предлагай простые варианты, соответствующие обстоятельствам, которые пользователь назвал. Не считай отдых единственно правильным решением и не отправляй автоматически закрывать глаза, дышать или сидеть в тишине. Если у неё есть пять минут и она не знает, как их использовать, предложи на выбор небольшую передышку или одно маленькое дело — без давления и длинных инструкций. Не предполагай, что вокруг тихо, дети заняты или есть свободное время.",
    },
    "wins": {
        "label": "🌷 Хочу вспомнить свои маленькие победы",
        "instruction": "Помогай заметить реальные события через один бережный и конкретный вопрос, если он уместен. Не убеждай, что пользователь обязательно сделала что-то великое, и не придумывай достижения. Если ей трудно вспомнить что-то полезное, не усиливай чувство вины и не дави повторными вопросами; можно спокойно признать, что сейчас ей сложно что-либо выделить.",
    },
}
support_sessions: dict[int, str] = {}
SUPPORT_STYLE = (
    "Общайся тепло, естественно и конкретно — как внимательная подруга, а не по психологическому скрипту. Отвечай на то, что мама действительно сказала, простым разговорным языком. Не приписывай ей чувства, страхи, мотивы, обстоятельства или достижения, которых нет в её сообщениях и истории. Не превращай короткую реплику в общий монолог о материнстве, усталости или одиночестве. Не пересказывай сообщение длинно и не используй канцелярские или абстрактные обороты, если можно сказать проще. Обычно достаточно одного содержательного абзаца, иногда двух; длина зависит от смысла, не от жёсткого лимита. Не добавляй несколько сообщений с повторяющимися рассуждениями, если можно ответить цельно. Не заканчивай каждую реплику вопросом и не превращай диалог в допрос. Не давай советов автоматически: если мама хочет выговориться, выслушай без советов; если просит совета, предложи один-два конкретных реалистичных шага, учитывая её обстоятельства. Не навязывай отдых, дыхательные практики или делегирование. Не хвали автоматически и не придумывай достижения. Избегай повторяющихся шаблонов вроде «я внимательно тебя слушаю», «я рядом», «ты имеешь право отдыхать», «давай выдохнем»; не добавляй обязательные сердечки или цветы. Учитывай историю разговора, не повторяй стартовый ответ после каждой реплики. Сценарий меняется только после явного выбора пользователя; при смене сценария сохраняй полезный контекст, но отвечай согласно новому запросу. Не объявляй «сценарий принят», если это не нужно для понимания интерфейса. Не рекламируй Greenway, товары, услуги или ссылки. Не ставь диагнозы и не обещай гарантированный результат. При непосредственной опасности для себя или другого человека бережно посоветуй немедленно обратиться в местную экстренную службу и к надёжному человеку рядом, не оставаться в одиночестве и по возможности отойти от средств причинения вреда."
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
    support_sessions.pop(user_id, None)
    banner_ids = (
        BANNER_SUPPORT[support_banner_index:] + BANNER_SUPPORT[:support_banner_index]
    ) if BANNER_SUPPORT else []
    if BANNER_SUPPORT:
        support_banner_index = (support_banner_index + 1) % len(BANNER_SUPPORT)

    caption = (
        "🫂 <b>Тёплая поддержка</b>\n\n"
        "Как тебе сейчас хотелось бы, чтобы я была рядом? Выбери подходящий вариант. "
        "Можно передумать или просто написать мне своими словами 💛"
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
    "🫂 <b>Тёплая поддержка</b> — поддержу и напомню выпить горячий чай ☕️\n\n"
    "<b>С чего начнём сегодня? Выбирай кнопку внизу 👇</b>"
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
- «🍲 Накормить семью»: предлагай простые, сытные и аппетитные семейные блюда из обычных недорогих продуктов, которые легко найти в ближайшем магазине или часто уже есть дома. Главный приоритет — минимум активного времени у плиты: обычно 15–30 минут, без сложных техник, редких ингредиентов и горы посуды. Если блюдо требует долгого запекания или варки, честно укажи общее время и по возможности предложи более быстрый вариант. Не начинай ответы с выдуманных сезонных вступлений вроде «лето, солнышко, жара»; упоминай сезон только если это действительно уместно и соответствует текущей дате.
- РАЗНООБРАЗИЕ: учитывай предыдущие блюда в истории диалога и не предлагай снова то же блюдо или почти такой же рецепт. Чередуй основы и способы приготовления: курица, фарш, яйца, творог, овощи, крупы, макароны, супы, запеканки, блюда на сковороде, салаты и простые блюда без мяса. Не делай каждый рецепт пастой, оладьями или курицей; меняй вкус, основные продукты и формат блюда. Не выдумывай, какие продукты есть у пользователя.
- Только в ответах рубрики «🍲 Накормить семью» в самом конце задай один короткий дружелюбный вопрос о продуктах, которые уже есть дома. Например: «Хочешь, подберём блюдо из того, что уже есть? Напиши, какие продукты у тебя сейчас в холодильнике 😊». В остальных рубриках НЕ задавай вопрос про продукты и НЕ добавляй предложение подобрать блюдо; заканчивай ответ по теме выбранной рубрики.
- «📦 Разгрести хаос»: экспресс-уборка за 5–15 минут БЕЗ едкой химии и БЕЗ дедовских методов (никакой соды, уксуса и горчичного порошка!). Рекомендуй эстетичный эко-подход в стиле Greenway: салфетки и файберы из микроволокна (работают от одной воды, убирают жир и грязь без капли химии), натуральную очищающую пасту или кислородный эко-очиститель для сложных пятен.
- «📅 День по полочкам»: план ориентирован на маму и сочетает заботу о детях, домашние дела и отдых, но не выдумывает обстоятельства семьи. Учитывай известный контекст: если известно, что у мамы младенец или малыш, предусматривай гибкие окна для кормлений, прогулки и возможного дневного сна, помня, что планы могут часто меняться и ребёнок не обязан долго занимать себя самостоятельно. Если дети старше и известны школа, детский сад или занятия, учитывай их. Если возраст и режим неизвестны, предложи гибкий план для мамы с блоками заботы о детях, бытовых дел и отдыха — без выдуманных расписаний, возрастов и обязательств. Если для полезного плана действительно не хватает важной информации, задай один короткий вопрос; не превращай ответ в анкету. Временные блоки — ориентир: предлагай переносить дела, сокращать список и менять порядок по потребностям детей и состоянию мамы. Пиши короткими абзацами, тепло, на «ты», с лёгким юмором и без чувства вины. Не обещай, что всё обязательно будет выполнено, и не превращай правила продуктивности в обязательные нормы. Не вставляй рекламу автоматически. Greenway упоминай только если пользователь сам спрашивает или рекомендация действительно уместна; объясняй конкретно и естественно, без расплывчатых фраз вроде «полезный напиток вот отсюда» и без необоснованных обещаний пользы для здоровья. Если даёшь ссылку, используй действующую реферальную ссылку из правил ниже.
- «💖 Тёплая поддержка»: следуй выбранному сценарию из SUPPORT_SCENARIOS. Будь естественной, не используй постоянные обращения «милая», «дорогая», не выдумывай чувства или обстоятельства, не давай непрошеных советов и не рекламируй товары. При непосредственной опасности направь к местной экстренной помощи и надёжному человеку рядом.

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

inline_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🍳 Накормить семью", callback_data="menu_food")],
        [InlineKeyboardButton(text="🧹 Разгрести хаос", callback_data="menu_clean")],
        [InlineKeyboardButton(text="📋 День по полочкам", callback_data="menu_plan")],
        [InlineKeyboardButton(text="🫂 Тёплая поддержка", callback_data="menu_support")],
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
    labels = {1: "старший ребёнок", 2: "второй ребёнок", 3: "третий ребёнок"}
    lines = []
    for age in ages:
        child_number = int(age["child_number"])
        label = labels.get(child_number, f"ребёнок №{child_number}")
        lines.append(f"• {label}: {format_child_age(age)}")
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
        with sqlite3.connect(STATE_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM user_names")
            total_users = cursor.fetchone()[0]

            cursor.execute("SELECT name FROM user_names ORDER BY rowid DESC LIMIT 5")
            recent_names = [row[0] for row in cursor.fetchall() if row[0]]

        names_preview = ", ".join(recent_names) if recent_names else "пока нет"

        stats_text = (
            "📊 <b>Статистика бота «Мама 24/7»:</b>\n\n"
            f"👥 Всего пользователей: <b>{total_users}</b>\n"
            f"🎯 Цель до платной версии: <b>100</b> (осталось {max(0, 100 - total_users)})\n\n"
            f"🌸 <i>Последние гости:</i> {names_preview}"
        )
        await message.answer(stats_text, parse_mode=ParseMode.HTML)

    except Exception as err:
        logger.exception("Stats error: %s", err)
        await message.answer(f"Ошибка получения статистики: {err}")



@dispatcher.message(F.photo)
async def handle_admin_photo(message: Message) -> None:
    if (
        message.from_user is None
        or message.from_user.id != ADMIN_ID
        or message.chat.type != "private"
        or not message.photo
    ):
        return

    photo_file_id = message.photo[-1].file_id
    await message.answer(
        f"Вот file_id твоего фото:\n<code>{photo_file_id}</code>",
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


async def start_chaos_flow(message: Message) -> None:
    global chaos_session_counter, clean_banner_index
    user_id = message.from_user.id if message.from_user else message.chat.id
    previous = chaos_sessions.pop(user_id, None)
    if previous and previous.get("timer_task"):
        previous["timer_task"].cancel()

    chaos_session_counter = (chaos_session_counter + 1) % 1000000
    session_id = chaos_session_counter
    chaos_sessions[user_id] = {
        "id": session_id,
        "stage": "zone",
        "active": True,
        "busy": False,
        "step_number": 0,
        "step_index": 0,
        "last_task": "",
        "last_message": None,
        "started_at": None,
        "duration": None,
        "timer_task": None,
    }
    banner_ids = BANNER_CLEAN[clean_banner_index:] + BANNER_CLEAN[:clean_banner_index]
    clean_banner_index = (clean_banner_index + 1) % len(BANNER_CLEAN)
    await answer_with_banner(
        message,
        "Давай разберём хаос маленькими шагами — без гонки и чувства вины 🌿\n\n<b>С чего начнём?</b>",
        banner_ids,
        reply_markup=chaos_keyboard(session_id, "zone"),
        parse_mode=ParseMode.HTML,
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
        await message.answer("Эта кнопка уже устарела 🌿 Если захочешь начать заново, выбери «📦 Разгрести хаос» в меню.")
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


@dispatcher.callback_query(F.data.startswith("support:"))
async def process_support_action(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    data = callback.data or ""
    user_id = callback.from_user.id
    if data == "support:home":
        support_sessions.pop(user_id, None)
        await replace_callback_message(callback)
        await callback.message.answer(
            "🏠 Главное меню. Выбирай, чем помочь:",
            reply_markup=MENU_KEYBOARD,
        )
        return
    if data == "support:choose_again":
        support_sessions.pop(user_id, None)
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
    support_sessions[user_id] = key
    scenario = SUPPORT_SCENARIOS[key]
    await replace_callback_message(callback)
    await answer_with_gemini(
        callback.message,
        "Ты выбрала сценарий: " + scenario["label"] + ".\n" + SUPPORT_STYLE + "\n"
        + scenario["instruction"] + "\n\n"
        + "Первый ответ должен быть полноценным ответом по выбранному сценарию, а не подтверждением выбора или заглушкой. Если контекста мало, не выдумывай его, но всё равно помоги по существу. "
        + "Отвечай только на подтверждённые детали, не додумывай чувства, обстоятельства или достижения. Не обязательно задавать вопрос в конце. Для сценария «Мне нужно выговориться» не советуй. Не рекламируй товары.",
        support_mode=True,
        request_user_id=user_id,
    )


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
) -> str:
    # Поддержка получает отдельную системную инструкцию: общие правила
    # рецептов/планов и обязательного ===SPLIT=== здесь мешали естественному ответу.
    if support_mode:
        return (
            "Ты — тёплая, внимательная собеседница в рубрике поддержки «Мама 24/7». "
            "Отвечай на русском, естественно и по-человечески, без психологического скрипта. "
            "Руководствуйся выбранным сценарием и всей доступной историей разговора. "
            "Реагируй на конкретные слова пользователя; не выдумывай чувства, мотивы, "
            "обстоятельства, заслуги или события. Не превращай короткую реплику в общий "
            "монолог о материнстве. Не давай советов, если их не просили; не навязывай отдых, "
            "дыхательные практики, делегирование или действия для заботы о себе. "
            "Не хвали автоматически, не повторяй шаблонные фразы, не задавай вопрос в конце "
            "каждого ответа. Если выбран сценарий тёплых слов — дай сами тёплые слова, "
            "а не уточняющий вопрос. Если выбран сценарий передышки — предложи несколько "
            "уместных вариантов только с учётом известных обстоятельств, не считая отдых "
            "единственно правильным. Если выбран сценарий маленьких побед — помоги заметить "
            "только реальные события, ничего не придумывай и не дави. Обычно ответ — один "
            "цельный абзац, иногда два. Не используй метку ===SPLIT===, не дели ответ на "
            "скрытые части, не добавляй меню действий и не рекламируй товары или услуги. "
            "Не используй имя, если оно неестественно звучит в обращении. "
            "При непосредственной опасности для себя или другого человека бережно посоветуй "
            "немедленно обратиться в местную экстренную службу и к надёжному человеку рядом."
        )

    # Для остальных рубрик сохраняем прежние общие правила и оформление.
    usable_name = user_name if user_name and re.fullmatch(r"[А-Яа-яЁё-]+", user_name) else None
    user_greeting = (
        f"6. Собеседницу зовут {usable_name}. Если обращаешься по имени, используй ТОЛЬКО это имя без изменения формы: не придумывай уменьшительные, ласкательные или искажённые варианты (например, из «Анна» нельзя делать «Аннешка»). Если имя звучит неестественно в обращении, просто скажи «дорогая» или ответь без имени. Не ставь обращение в каждое сообщение.\n"
        if usable_name
        else "6. Обращайся к собеседнице тепло и по-доброму (милая, дорогая). Если имя записано латиницей, не произноси его в русскоязычном ответе.\n"
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
    support_mode: bool = False,
) -> str:
    # Повторные попытки выполняются в answer_with_gemini, поэтому здесь
    # не создаём ещё один вложенный цикл, который надолго задерживает ответ.
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=personalized_system_prompt(user_name, support_mode=support_mode),
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
) -> None:
    user_id = request_user_id or (message.from_user.id if message.from_user else message.chat.id)
    if prompt is None and voice_file_id is None:
        return
    # В поддержке ответ должен оставаться цельным, без скрываемой второй части.
    if support_mode:
        ignore_split = True

    async with get_user_request_lock(user_id):
        temporary_message = await send_thinking_message(message)
        try:
            if voice_file_id is not None:
                audio_bytes = await download_voice_audio(voice_file_id)
                user_content = voice_user_content(audio_bytes)
            else:
                user_content = text_user_content(prompt or "")

            history = conversation_history_by_user.get(user_id, [])
            if support_mode:
                scenario = SUPPORT_SCENARIOS.get(support_sessions.get(user_id, ""), {})
                mode_context = (
                    SUPPORT_STYLE + "\n\nТЕКУЩИЙ СЦЕНАРИЙ: "
                    + scenario.get("instruction", "")
                    + "\n\nПродолжай естественный разговор с учётом всей доступной истории. "
                    "Отвечай на последнюю реплику, включая новые подробности; не повторяй стартовый ответ. "
                    "Не используй общий совет вместо реакции на конкретную ситуацию. "
                    "Если пользователь просит только выслушать — не советуй. Не рекламируй товары."
                )
                if voice_file_id is None:
                    user_content = text_user_content(
                        mode_context + "\n\nСообщение мамы: " + (prompt or "")
                    )
                else:
                    user_content = types.Content(
                        role="user",
                        parts=[*user_content.parts, types.Part.from_text(text=mode_context)],
                    )
            request_contents = [*history, user_content]
            reply = None

            for attempt in range(2):
                try:
                    reply = await asyncio.to_thread(
                        generate_reply,
                        request_contents,
                        user_names.get(user_id),
                        support_mode=support_mode,
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
            await send_final_response(
                message,
                reply,
                banner_ids=banner_ids,
                food_followup=food_followup,
                ignore_split=ignore_split,
                plan_flow=plan_flow,
                support_mode=support_mode,
            )
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
