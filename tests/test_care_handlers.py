import unittest

from handlers_care import (
    CareStates,
    _photo_prompt,
    _quiz_prompt,
    care_mode_keyboard,
    care_quiz_keyboard,
    care_result_keyboard,
)


class CareHandlerStructureTests(unittest.TestCase):
    def test_fsm_contains_required_stages(self):
        self.assertEqual(
            {state.state.split(":")[-1] for state in (
                CareStates.waiting_for_mode,
                CareStates.waiting_for_payment,
                CareStates.waiting_for_photo,
                CareStates.survey_skin_type,
                CareStates.survey_concern,
                CareStates.survey_brand_pref,
                CareStates.generating_result,
            )},
            {
                "waiting_for_mode", "waiting_for_payment", "waiting_for_photo",
                "survey_skin_type", "survey_concern", "survey_brand_pref",
                "generating_result",
            },
        )

    def test_paid_user_gets_two_distinct_modes(self):
        rows = care_mode_keyboard("order-123").inline_keyboard
        self.assertIn("care:mode:photo:order-123", rows[0][0].callback_data)
        self.assertIn("care:mode:quiz:order-123", rows[1][0].callback_data)

    def test_quiz_is_button_only_and_has_three_question_sets(self):
        self.assertEqual(len(care_quiz_keyboard("skin", "order-123").inline_keyboard), 5)
        self.assertEqual(len(care_quiz_keyboard("concern", "order-123").inline_keyboard), 6)
        self.assertEqual(len(care_quiz_keyboard("brand", "order-123").inline_keyboard), 5)

    def test_photo_and_quiz_prompts_include_safety_limits(self):
        self.assertIn("Не ставь диагнозы", _photo_prompt())
        self.assertIn("Не ставь медицинские диагнозы", _quiz_prompt({
            "skin_type": "Жирная / пористая",
            "concern": "Поры, чёрные точки, блеск",
            "brand_pref": "Не принципиально",
        }))

    def test_result_keyboard_offers_repeat_without_checkout(self):
        callbacks = [
            button.callback_data
            for row in care_result_keyboard("order-123").inline_keyboard
            for button in row
        ]
        self.assertIn("care:repeat:order-123", callbacks)
        self.assertFalse(any("payment" in (value or "") for value in callbacks))


if __name__ == "__main__":
    unittest.main()
