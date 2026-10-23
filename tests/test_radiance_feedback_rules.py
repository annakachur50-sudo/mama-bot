import ast
import html
import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def load_function(name):
    node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = {"html": html, "re": re}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "main.py", "exec"), namespace)
    return namespace[name]


class RadianceFeedbackRulesTests(unittest.TestCase):
    def test_vision_formatter_converts_bold_and_escapes_dynamic_text(self):
        formatter = load_function("radiance_result_html")
        rendered = formatter("**Палитра**: <b>не доверять</b> & «шалфей»")
        self.assertIn("<b>Палитра</b>", rendered)
        self.assertIn("&lt;b&gt;не доверять&lt;/b&gt;", rendered)
        self.assertIn("&amp;", rendered)
        self.assertNotIn("**", rendered)

    def test_feedback_header_handles_missing_username_and_escapes_username(self):
        header = load_function("feedback_header")
        class User:
            id = 12345
            username = None
        self.assertIn("без username", header(User()))
        self.assertIn("12345", header(User()))
        User.username = "name<&"
        self.assertIn("@name&lt;&amp;", header(User()))

    def test_feedback_escaping_stays_within_limit_without_breaking_entities(self):
        escape_content = load_function("escape_feedback_content")
        rendered = escape_content("<" * 100, 20)
        self.assertLessEqual(len(rendered), 20)
        self.assertTrue(rendered.startswith("&lt;"))
        self.assertNotIn("&l…", rendered)

    def test_feedback_uses_existing_channel_and_state_gates_forwarding(self):
        self.assertIn("LOG_CHANNEL_ID = -1004353307194", SOURCE)
        self.assertIn('feedback_states.get(user_id) == "waiting_for_feedback"', SOURCE)
        self.assertIn("feedback_inflight", SOURCE)
        self.assertIn("feedback_sent_events", SOURCE)
        self.assertIn("async def send_channel_notification(", SOURCE)
        self.assertIn("await send_channel_notification(", SOURCE)
        self.assertIn("photo=message.photo[-1].file_id", SOURCE)
        self.assertIn('callback_data="feedback:cancel"', SOURCE)

    def test_vision_response_is_sent_as_html(self):
        self.assertIn("parse_mode=ParseMode.HTML", SOURCE)
        self.assertIn("formatted_result = radiance_result_html(result)", SOURCE)


if __name__ == "__main__":
    unittest.main()
