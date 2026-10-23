import ast
import html
import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
NODE = next(node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name == "radiance_text_to_html")
NAMESPACE = {"re": re, "html": html}
exec(compile(ast.Module(body=[NODE], type_ignores=[]), "main.py", "exec"), NAMESPACE)

class RadianceFormattingTests(unittest.TestCase):
    def test_bold_markers_become_html_and_text_is_escaped(self):
        rendered = NAMESPACE["radiance_text_to_html"]("**Палитра** <script>alert(1)</script>")
        self.assertEqual(rendered, "<b>Палитра</b> &lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotIn("**", rendered)

    def test_plain_text_and_multiline_bold(self):
        rendered = NAMESPACE["radiance_text_to_html"]("🌿 Шалфей\n**Почему подходит\nтебе**")
        self.assertEqual(rendered, "🌿 Шалфей\n<b>Почему подходит\nтебе</b>")

    def test_feedback_routes_only_in_active_state_and_reuses_channel(self):
        self.assertIn('feedback_states[user_id] = "waiting_for_feedback"', SOURCE)
        self.assertIn("chat_id=LOG_CHANNEL_ID", SOURCE)
        self.assertIn("async def process_feedback_message", SOURCE)
        self.assertIn("feedback_processed_messages", SOURCE)
        self.assertIn('callback_data="feedback:cancel"', SOURCE)

if __name__ == "__main__":
    unittest.main()
