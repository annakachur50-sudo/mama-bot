import ast
import html
import re
import unittest
from pathlib import Path

SOURCE = Path("main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def load_radiance_formatter():
    node = next(
        item for item in TREE.body
        if isinstance(item, ast.FunctionDef) and item.name == "radiance_markdown_to_html"
    )
    namespace = {"html": html, "re": re}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "main.py", "exec"), namespace)
    return namespace["radiance_markdown_to_html"]


class RadianceFormattingTests(unittest.TestCase):
    def test_markdown_bold_becomes_telegram_html(self):
        convert = load_radiance_formatter()
        self.assertEqual(convert("Цвет: **мягкий шалфей** 🌿"), "Цвет: <b>мягкий шалфей</b> 🌿")

    def test_model_text_is_html_escaped(self):
        convert = load_radiance_formatter()
        self.assertEqual(convert("**<b>пример</b>**"), "<b>&lt;b&gt;пример&lt;/b&gt;</b>")
        self.assertEqual(convert("<i>не тег</i>"), "&lt;i&gt;не тег&lt;/i&gt;")

    def test_unmatched_markers_do_not_leak(self):
        self.assertNotIn("**", load_radiance_formatter()("текст ** без пары"))

    def test_vision_prompt_has_palette_and_soft_lighting_rules(self):
        start = SOURCE.index("def analyze_radiance_photo_sync(")
        end = SOURCE.index("\n\ndef radiance_markdown_to_html(", start)
        prompt = SOURCE[start:end]
        self.assertIn("не отказывайся от полезного разбора из-за обычного домашнего освещения", prompt)
        for shade in ("🌿 Мягкий шалфей", "🌸 Пыльная роза", "☕ Какао с молоком", "🌊 Морская волна"):
            self.assertIn(shade, prompt)

    def test_vision_result_uses_html_parse_mode(self):
        start = SOURCE.index("async def handle_admin_photo(")
        end = SOURCE.index('@dispatcher.message(Command("testfoodphoto"))', start)
        handler = SOURCE[start:end]
        self.assertIn("radiance_markdown_to_html(result)", handler)
        self.assertIn("parse_mode=ParseMode.HTML", handler)

    def test_feedback_uses_existing_channel_and_menu_button_once(self):
        self.assertIn("LOG_CHANNEL_ID = -1004353307194", SOURCE)
        self.assertIn("chat_id=LOG_CHANNEL_ID", SOURCE)
        self.assertEqual(SOURCE.count("💌 Написать нам / Поддержка"), 1)
        self.assertIn('FEEDBACK_STATE = "waiting_for_feedback"', SOURCE)
        self.assertIn('callback_data="feedback:cancel"', SOURCE)

    def test_feedback_routes_text_and_photo_only_during_active_state(self):
        text_start = SOURCE.index("async def handle_text(")
        text_end = SOURCE.index("\nasync def main()", text_start)
        text_handler = SOURCE[text_start:text_end]
        photo_start = SOURCE.index("async def handle_admin_photo(")
        photo_end = SOURCE.index('@dispatcher.message(Command("testfoodphoto"))', photo_start)
        photo_handler = SOURCE[photo_start:photo_end]
        self.assertIn("if feedback_states.get(user_id) == FEEDBACK_STATE", text_handler)
        self.assertIn("if feedback_states.get(user_id) == FEEDBACK_STATE", photo_handler)


if __name__ == "__main__":
    unittest.main()
