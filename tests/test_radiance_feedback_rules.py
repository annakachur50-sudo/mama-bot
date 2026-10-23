import ast
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
        self.assertIn(
            "status_message.edit_text(radiance_result_to_html(result), "
            "reply_markup=radiance_result_keyboard(), parse_mode=ParseMode.HTML)",
            photo_handler,
        )
        self.assertIn(
            "message.answer(radiance_result_to_html(result), "
            "reply_markup=radiance_result_keyboard(), parse_mode=ParseMode.HTML)",
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
