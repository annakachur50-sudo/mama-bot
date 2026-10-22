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
        self.assertEqual(band(36)[0], "2–4 года")
        self.assertEqual(band(84)[0], "5–9 лет")
        self.assertEqual(band(132)[0], "10–12 лет")
        self.assertEqual(band(168)[0], "13–15 лет")

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
        self.assertIn("generate_kids_activity_sync(ages, previous)", SOURCE)
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


if __name__ == "__main__":
    unittest.main()
