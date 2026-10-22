import ast
import unittest
from pathlib import Path

SOURCE = Path("main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def load_helpers():
    wanted = {"kids_age_months", "kids_age_band", "kids_picker_label"}
    nodes = [node for node in TREE.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "main.py", "exec"), namespace)
    return namespace


HELPERS = load_helpers()


def age(years):
    return {"child_number": 1, "age_value": years, "age_unit": "years"}


class KidsAgeRulesTests(unittest.TestCase):
    def test_age_bands_for_requested_samples(self):
        band = HELPERS["kids_age_band"]
        self.assertEqual(band(18)[0], "до 2 лет")
        self.assertEqual(band(36)[0], "2–4 года")
        self.assertEqual(band(84)[0], "5–9 лет")
        self.assertEqual(band(132)[0], "10–12 лет")
        self.assertEqual(band(168)[0], "13–15 лет")
        self.assertEqual(band(192)[0], "16–17 лет")

    def test_live_button_labels(self):
        label = HELPERS["kids_picker_label"]
        self.assertEqual(label(age(1)), "👶 Малыш")
        self.assertEqual(label(age(3)), "🧒 Кроха")
        self.assertEqual(label(age(7)), "🧩 Ребёнок")
        self.assertEqual(label(age(11)), "🎯 Старший")
        self.assertEqual(label(age(14)), "🎧 Подросток")
        self.assertEqual(label(age(16)), "✨ Старший подросток")

    def test_exact_selected_age_is_sent_to_gemini(self):
        self.assertIn("format_child_age(age)", SOURCE)
        self.assertIn("kids_age_months(age)", SOURCE)
        self.assertIn("await kids_activity_for_age(selected_age, callback.from_user.id)", SOURCE)
        self.assertIn('int(age["child_number"]) == child_number', SOURCE)

    def test_joint_prompt_includes_every_participant(self):
        self.assertIn("asyncio.to_thread(generate_kids_activity_sync, ages, previous)", SOURCE)
        self.assertIn("для всех перечисленных возрастов", SOURCE)
        self.assertIn("разные роли/уровни сложности", SOURCE)

    def test_teen_prompt_excludes_childish_games_by_default(self):
        self.assertIn("для 13–17 лет запрещены примитивные детские игры", SOURCE)
        self.assertIn("кроме случая, когда сам подросток явно попросил", SOURCE)

    def test_duplicate_ages_have_distinguishing_labels(self):
        self.assertIn("первый", SOURCE)
        self.assertIn("второй", SOURCE)
        self.assertIn("третий", SOURCE)
        self.assertNotIn("Ребёнок №", SOURCE)

    def test_radiance_status_precedes_vision_call_and_handles_result(self):
        handler_start = SOURCE.index("async def handle_admin_photo(")
        handler_end = SOURCE.index('@dispatcher.message(Command("testfoodphoto"))', handler_start)
        handler = SOURCE[handler_start:handler_end]
        self.assertIn("Секундочку, любуюсь твоим фото и подбираю идеальную палитру... ✨", handler)
        self.assertLess(handler.index("status_message = await message.answer("), handler.index("analyze_radiance_photo_sync"))
        self.assertIn("status_message.edit_text(result", handler)
        self.assertIn("status_message.edit_text(error_text", handler)
        self.assertIn("await message.answer(error_text", handler)

    def test_radiance_prompt_is_plain_and_grounded(self):
        start = SOURCE.index("def analyze_radiance_photo_sync(")
        end = SOURCE.index("\n\nasync def start_kids_flow(", start)
        prompt = SOURCE[start:end]
        self.assertIn("живого, доброжелательного комплимента", prompt)
        self.assertIn("Не выдумывай черты внешности", prompt)
        self.assertIn("4–5 подходящих оттенков", prompt)
        self.assertIn("1–2 оттенка", prompt)
        self.assertIn("Не повторяй предупреждение о дневном свете", prompt)

    def test_16_plus_uses_senior_teen_label(self):
        label = HELPERS["kids_picker_label"]
        self.assertEqual(label(age(16)), "✨ Старший подросток")
        self.assertEqual(label(age(18)), "✨ Старший подросток")


if __name__ == "__main__":
    unittest.main()
