import ast
import html
import re
import unittest
from pathlib import Path

SOURCE = Path("main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def formatter():
    node = next(
        item for item in TREE.body
        if isinstance(item, ast.FunctionDef) and item.name == "format_kids_activity_html"
    )
    namespace = {"html": html, "re": re}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "main.py", "exec"), namespace)
    return namespace["format_kids_activity_html"]


class KidsRiddleSpoilerTests(unittest.TestCase):
    def setUp(self):
        self.format = formatter()

    def test_ordinary_detective_answer_is_last_and_spoiler_wrapped(self):
        result = self.format(
            "🕵️ «Кто взял ключ?» (8 лет)\nУ двери мокрые следы, а на улице дождь.\nКто был снаружи?\n💡 Отгадка для мамы: по этим данным нельзя однозначно определить человека, поэтому нужно выбрать другую загадку.",
            "8 лет",
        )
        self.assertIn("<tg-spoiler>по этим данным нельзя однозначно определить человека, поэтому нужно выбрать другую загадку.</tg-spoiler>", result)
        self.assertIn("parse_mode=ParseMode.HTML", SOURCE)

    def test_danetka_prompt_requires_one_answer_for_teens(self):
        start = SOURCE.index("def generate_kids_activity_sync(")
        end = SOURCE.index("\n\nasync def kids_activity_for_age(", start)
        prompt = SOURCE[start:end]
        self.assertIn("ОБЯЗАТЕЛЬНАЯ ОТГАДКА", prompt)
        self.assertIn("для любого возраста, включая подростков и совместную игру", prompt)
        self.assertIn("одним чётким ответом", prompt)
        self.assertIn("Не добавляй альтернативные версии в скобках", prompt)
        self.assertIn("Если однозначность обеспечить нельзя, выбери другую задачу", prompt)

    def test_joint_game_answer_uses_spoiler_marker(self):
        result = self.format(
            "🧩 «Данетка» (6 и 13 лет)\nИстория и вопрос для всей семьи.\n💡 Отгадка для мамы: Он ехал в лифте только до своего этажа.",
            "6 и 13 лет",
        )
        self.assertIn("💡 Отгадка для мамы: <tg-spoiler>Он ехал в лифте только до своего этажа.</tg-spoiler>", result)
        self.assertTrue(result.rstrip().endswith("</tg-spoiler>"))

    def test_non_riddle_activity_has_no_spoiler(self):
        result = self.format(
            "🎨 «Три цвета» (9 лет)\nНарисуйте постер, используя три цвета.\nПопроси ребёнка рассказать о рисунке.",
            "9 лет",
        )
        self.assertNotIn("Отгадка для мамы", result)
        self.assertNotIn("<tg-spoiler>", result)

    def test_answer_special_characters_and_quotes_are_escaped_once(self):
        result = self.format(
            "🕵️ «Символы» (14 лет)\nРеши загадку.\n💡 Отгадка для мамы: A < B & B > C, ответ «ключ»",
            "14 лет",
        )
        self.assertIn("<tg-spoiler>A &lt; B &amp; B &gt; C, ответ «ключ»</tg-spoiler>", result)
        self.assertNotIn("A < B", result)
        self.assertNotIn("&amp;amp;", result)
        self.assertEqual(result.count("<tg-spoiler>"), 1)
        self.assertEqual(result.count("</tg-spoiler>"), 1)

    def test_telegram_html_parse_mode_is_used_for_game_result(self):
        start = SOURCE.index("async def send_kids_activity(")
        end = SOURCE.index("\n\n@dispatcher.callback_query", start)
        handler = SOURCE[start:end]
        self.assertIn("status_message.edit_text(result, reply_markup=keyboard, parse_mode=ParseMode.HTML)", handler)
        self.assertNotIn("ParseMode.MARKDOWN", handler)
        self.assertIn('escaped_answer = html.escape(answer, quote=True)', SOURCE)
        self.assertIn('f"{answer_prefix} <tg-spoiler>{escaped_answer}</tg-spoiler>"', SOURCE)


if __name__ == "__main__":
    unittest.main()
