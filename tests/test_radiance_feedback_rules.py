import ast
import asyncio
import html
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

SOURCE = Path("main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def load_helpers():
    wanted = {"radiance_result_to_html", "feedback_header"}
    nodes = [
        node for node in TREE.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    namespace = {"html": html, "re": re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "main.py", "exec"), namespace)
    return namespace


HELPERS = load_helpers()


class RadianceFormattingTests(unittest.TestCase):
    def test_markdown_bold_is_converted_to_html(self):
        result = HELPERS["radiance_result_to_html"](
            "**Мягкий шалфей**\n🌸 Пыльная роза"
        )
        self.assertEqual(result, "<b>Мягкий шалфей</b>\n🌸 Пыльная роза")
        self.assertNotIn("**", result)

    def test_raw_html_from_model_is_escaped(self):
        result = HELPERS["radiance_result_to_html"](
            "**Какао с молоком** <b>не доверенный тег</b> & текст"
        )
        self.assertEqual(
            result,
            "<b>Какао с молоком</b> &lt;b&gt;не доверенный тег&lt;/b&gt; &amp; текст",
        )
        self.assertNotIn("<b>не доверенный тег</b>", result)

    def test_vision_result_is_sent_with_html_parse_mode(self):
        photo_handler = SOURCE[
            SOURCE.index("async def handle_admin_photo("):
            SOURCE.index('@dispatcher.message(Command("testfoodphoto"))')
        ]
        self.assertIn("result = radiance_result_to_html(result)", photo_handler)
        self.assertIn(
            "status_message.edit_text(result, reply_markup=radiance_result_keyboard(), "
            "parse_mode=ParseMode.HTML)",
            photo_handler,
        )
        self.assertIn(
            "message.answer(result, reply_markup=radiance_result_keyboard(), parse_mode=ParseMode.HTML)",
            photo_handler,
        )

    def test_prompt_does_not_reject_ordinary_home_lighting(self):
        start = SOURCE.index("def analyze_radiance_photo_sync(")
        end = SOURCE.index("\n\ndef radiance_result_to_html(", start)
        prompt = SOURCE[start:end]
        self.assertIn("обычного домашнего освещения", prompt)
        self.assertIn("Сразу дай полезную предварительную", prompt)
        self.assertIn("🌿 Мягкий шалфей", prompt)
        self.assertIn("🌸 Пыльная роза", prompt)
        self.assertIn("☕ Какао с молоком", prompt)
        self.assertIn("🌊 Морская волна", prompt)
        self.assertIn("не выдавай приблизительный подбор за точное определение цветотипа", prompt)


class FakeFeedbackBot:
    def __init__(self, fail_send=False):
        self.fail_send = fail_send
        self.sent_messages = []
        self.sent_photos = []

    async def send_message(self, *args, **kwargs):
        if self.fail_send:
            raise RuntimeError("simulated channel send failure")
        self.sent_messages.append({"args": args, **kwargs})
        return SimpleNamespace(message_id=len(self.sent_messages))

    async def send_photo(self, *args, **kwargs):
        if self.fail_send:
            raise RuntimeError("simulated channel photo failure")
        self.sent_photos.append({"args": args, **kwargs})
        return SimpleNamespace(message_id=len(self.sent_photos))


class FakeFeedbackMessage:
    def __init__(self, bot, text=None, photo=None, caption=None, user=None, message_id=10):
        self.bot = bot
        self.text = text
        self.photo = photo or []
        self.caption = caption
        self.from_user = user or SimpleNamespace(id=42, username="test_mom")
        self.message_id = message_id
        self.replies = []

    async def answer(self, text, reply_markup=None, **kwargs):
        self.replies.append({"text": text, "reply_markup": reply_markup})


def load_feedback_runtime(fake_bot):
    wanted = {
        "feedback_header", "forward_feedback_to_channel", "process_feedback_message",
        "start_feedback_flow", "cancel_feedback_callback",
    }
    nodes = [
        node for node in TREE.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted
    ]

    async def send_channel_notification(text, parse_mode="HTML"):
        return await fake_bot.send_message(
            chat_id=-1004353307194,
            text=text,
            parse_mode=parse_mode,
        )

    namespace = {
        "html": html,
        "asyncio": asyncio,
        "Message": object,
        "CallbackQuery": object,
        "ParseMode": SimpleNamespace(HTML="HTML"),
        "LOG_CHANNEL_ID": -1004353307194,
        "feedback_states": {42: "waiting_for_feedback"},
        "radiance_states": {},
        "pending_kids_age": set(),
        "support_sessions": {},
        "feedback_processing_locks": {},
        "feedback_processed_messages": set(),
        "logger": SimpleNamespace(warning=lambda *args, **kwargs: None),
        "feedback_cancel_keyboard": lambda: "cancel",
        "inline_kb": "main-menu",
        "send_channel_notification": send_channel_notification,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "main.py", "exec"), namespace)
    return namespace


class FakeFeedbackCallback:
    def __init__(self, user_id, message):
        self.from_user = SimpleNamespace(id=user_id)
        self.message = message
        self.answered = False

    async def answer(self):
        self.answered = True


class FeedbackFlowRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_opening_feedback_sets_state_and_shows_cancel(self):
        bot = FakeFeedbackBot()
        runtime = load_feedback_runtime(bot)
        runtime["feedback_states"].clear()
        message = FakeFeedbackMessage(bot)
        await runtime["start_feedback_flow"](message, 42)

        self.assertEqual(runtime["feedback_states"][42], "waiting_for_feedback")
        self.assertIn("Напиши свои пожелания", message.replies[0]["text"])
        self.assertEqual(message.replies[0]["reply_markup"], "cancel")

    async def test_cancel_clears_state_and_returns_to_main_menu(self):
        bot = FakeFeedbackBot()
        runtime = load_feedback_runtime(bot)
        message = FakeFeedbackMessage(bot)
        callback = FakeFeedbackCallback(42, message)
        await runtime["cancel_feedback_callback"](callback)

        self.assertTrue(callback.answered)
        self.assertNotIn(42, runtime["feedback_states"])
        self.assertIn("обращение отменено", message.replies[0]["text"])
        self.assertEqual(message.replies[0]["reply_markup"], "main-menu")

    async def test_text_is_forwarded_and_state_clears_only_after_success(self):
        bot = FakeFeedbackBot()
        runtime = load_feedback_runtime(bot)
        message = FakeFeedbackMessage(bot, text="Пожалуйста, добавьте кнопку назад")
        handled = await runtime["process_feedback_message"](message)

        self.assertTrue(handled)
        self.assertEqual(len(bot.sent_messages), 1)
        sent = bot.sent_messages[0]
        self.assertEqual(sent["chat_id"], -1004353307194)
        self.assertIn("@test_mom", sent["text"])
        self.assertIn("ID: <code>42</code>", sent["text"])
        self.assertIn("Пожалуйста, добавьте кнопку назад", sent["text"])
        self.assertEqual(runtime["feedback_states"], {})
        self.assertIn("Спасибо за тепло и обратную связь", message.replies[-1]["text"])

    async def test_photo_and_user_caption_are_forwarded_together(self):
        bot = FakeFeedbackBot()
        runtime = load_feedback_runtime(bot)
        message = FakeFeedbackMessage(
            bot,
            photo=[SimpleNamespace(file_id="photo-file-id")],
            caption="На экране ошибка: <не открывается>",
        )
        await runtime["process_feedback_message"](message)

        self.assertEqual(len(bot.sent_photos), 1)
        sent = bot.sent_photos[0]
        self.assertEqual(sent["photo"], "photo-file-id")
        self.assertIn("Новое сообщение от пользователя", sent["caption"])
        self.assertIn("На экране ошибка: &lt;не открывается&gt;", sent["caption"])
        self.assertEqual(sent["parse_mode"], "HTML")

    async def test_failed_channel_send_keeps_feedback_open_and_does_not_claim_success(self):
        bot = FakeFeedbackBot(fail_send=True)
        runtime = load_feedback_runtime(bot)
        message = FakeFeedbackMessage(bot, text="Это сообщение должно остаться неподтверждённым")
        await runtime["process_feedback_message"](message)

        self.assertEqual(runtime["feedback_states"][42], "waiting_for_feedback")
        self.assertTrue(any("Не получилось передать обращение" in item["text"] for item in message.replies))
        self.assertFalse(any("Спасибо за тепло и обратную связь" in item["text"] for item in message.replies))

    async def test_reprocessing_the_same_message_does_not_forward_twice(self):
        bot = FakeFeedbackBot()
        runtime = load_feedback_runtime(bot)
        message = FakeFeedbackMessage(bot, text="Одна отправка", message_id=77)
        await runtime["process_feedback_message"](message)
        await runtime["process_feedback_message"](message)

        self.assertEqual(len(bot.sent_messages), 1)
        self.assertEqual(len(message.replies), 1)


class FeedbackFlowTests(unittest.TestCase):
    def test_feedback_header_handles_username_and_missing_username(self):
        header = HELPERS["feedback_header"]
        self.assertEqual(
            header(SimpleNamespace(id=123, username="mama&co")),
            "💌 Новое сообщение от пользователя: <b>@mama&amp;co</b> (ID: <code>123</code>)",
        )
        self.assertEqual(
            header(SimpleNamespace(id=456, username=None)),
            "💌 Новое сообщение от пользователя: <b>без username</b> (ID: <code>456</code>)",
        )

    def test_feedback_uses_existing_channel_and_shared_sender(self):
        self.assertEqual(SOURCE.count("-1004353307194"), 1)
        self.assertIn("LOG_CHANNEL_ID = -1004353307194", SOURCE)
        self.assertIn("await send_channel_notification(notification_text)", SOURCE)
        self.assertIn("await send_channel_notification(combined_text)", SOURCE)
        self.assertIn("feedback_states[user_id] = \"waiting_for_feedback\"", SOURCE)

    def test_feedback_button_is_present_once_in_main_inline_menu(self):
        self.assertEqual(SOURCE.count('text="💌 Написать нам / Поддержка"'), 1)
        self.assertIn('callback_data="feedback:start"', SOURCE)
        self.assertIn('text="❌ Отмена", callback_data="feedback:cancel"', SOURCE)

    def test_photo_caption_and_failure_path_are_preserved(self):
        self.assertIn("caption = (message.caption or \"\").strip()", SOURCE)
        self.assertIn("photo=message.photo[-1].file_id", SOURCE)
        self.assertIn("Не получилось передать обращение", SOURCE)
        self.assertIn("feedback_states.pop(user_id, None)", SOURCE)
        self.assertIn("feedback_processed_messages", SOURCE)


if __name__ == "__main__":
    unittest.main()
