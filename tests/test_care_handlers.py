import ast
import unittest
from pathlib import Path


class CareHandlerStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path(__file__).resolve().parents[1] / "handlers_care.py"
        cls.source = cls.path.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, filename=str(cls.path))
        cls.definitions = {
            node.name: node
            for node in ast.walk(cls.tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }

    def test_fsm_contains_required_stages(self):
        self.assertIn("CareStates", self.definitions)
        for name in (
            "waiting_for_mode", "waiting_for_payment", "waiting_for_photo",
            "survey_skin_type", "survey_concern", "survey_brand_pref",
            "generating_result",
        ):
            self.assertIn(f"{name} = State()", self.source)

    def test_paid_user_gets_two_distinct_modes(self):
        self.assertIn("care:mode:photo:{order_id}", self.source)
        self.assertIn("care:mode:quiz:{order_id}", self.source)
        self.assertIn("Анализ кожи по селфи", self.source)
        self.assertIn("Ответить на 3 вопроса", self.source)

    def test_paid_care_mode_keyboard_has_exact_choices_and_radiance_back(self):
        from handlers_care import CARE_MODE_INTRO_TEXT, care_mode_keyboard

        keyboard = care_mode_keyboard("order-123")
        buttons = [button for row in keyboard.inline_keyboard for button in row]
        self.assertIn("Твой персональный AI-косметолог", CARE_MODE_INTRO_TEXT)
        self.assertEqual([button.text for button in buttons], [
            "📸 По фото лица",
            "📝 По быстрым вопросам",
            "⬅️ Назад в Сияние",
        ])
        self.assertEqual([button.callback_data for button in buttons], [
            "care:mode:photo:order-123",
            "care:mode:quiz:order-123",
            "menu_radiance",
        ])

    def test_quiz_is_button_only_and_has_three_question_sets(self):
        self.assertIn('"skin": [', self.source)
        self.assertIn('"concern": [', self.source)
        self.assertIn('"brand": [', self.source)
        self.assertIn("care:quiz:{question}:{key}:{order_id}", self.source)

    def test_photo_and_quiz_prompts_include_safety_limits(self):
        self.assertIn("не ставь диагнозы", self.source.lower())
        self.assertIn("не диагностируй заболевания", self.source.lower())
        self.assertIn("types.Part.from_bytes", self.source)

    def test_result_keyboard_offers_repeat_without_checkout(self):
        self.assertIn("care:repeat:{order_id}", self.source)
        self.assertIn("Повторить подбор", self.source)
        self.assertNotIn("care:payment", self.source)


if __name__ == "__main__":
    unittest.main()
