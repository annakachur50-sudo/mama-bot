import unittest

from handlers_care import (
    REF_LINK_GREENWAY,
    REF_LINK_SW,
    _format_result,
    _parse_care_response,
    _photo_prompt,
    _quiz_prompt,
    care_result_keyboard,
)


class CareProductMatrixTests(unittest.TestCase):
    def test_prompts_contain_only_the_agreed_catalog(self):
        for prompt in (_photo_prompt("эко"), _quiz_prompt({"skin_type": "сухая"})):
            for allowed in (
                "Greenway Cactus", "Experalta Biomelle", "Chronolong",
                "Experalta Platinum", "Anua", "Manyo Pure Cleansing Oil",
                "Round Lab", "Medicube", "La Roche-Posay", "CeraVe",
                "Art&Fact", "Icon Skin",
            ):
                with self.subTest(brand=allowed):
                    self.assertIn(allowed, prompt)
            self.assertIn("Greenway Hemp запрещён", prompt)
            self.assertIn("не выдумывай продукты", prompt.lower())
            self.assertIn("json", prompt.lower())

    def test_structured_response_filters_unapproved_brands_and_hides_hemp(self):
        raw = (
            '{"answer":"🌸 Уход\\nGreenway Cactus — мягкое увлажнение. '
            'Hemp не рекомендую.","recommended_brands":["Greenway","Hemp","Luxury"]}'
        )
        answer, brands = _parse_care_response(raw)
        self.assertIn("Greenway Cactus", answer)
        self.assertNotIn("Greenway Hemp", answer)
        self.assertEqual(brands, ["Greenway"])

    def test_greenway_only_shows_greenway_button(self):
        _, brands = _parse_care_response(
            '{"answer":"Greenway Cactus подойдёт для увлажнения.","recommended_brands":["Greenway"]}'
        )
        keyboard = care_result_keyboard("order-1", brands)
        buttons = [button for row in keyboard.inline_keyboard for button in row]
        urls = [button.url for button in buttons if button.url]
        self.assertEqual(urls, [REF_LINK_GREENWAY])
        self.assertIn("Повторить подбор", [button.text for button in buttons])
        self.assertIn("В главное меню", [button.text for button in buttons])

    def test_siberian_wellness_only_shows_sw_button(self):
        _, brands = _parse_care_response(
            '{"answer":"Siberian Wellness Experalta Biomelle поддерживает барьерный уход.",'
            '"recommended_brands":["Siberian Wellness"]}'
        )
        keyboard = care_result_keyboard("order-2", brands)
        urls = [button.url for row in keyboard.inline_keyboard for button in row if button.url]
        self.assertEqual(urls, [REF_LINK_SW])

    def test_both_brands_show_both_buttons_in_one_row(self):
        _, brands = _parse_care_response(
            '{"answer":"Greenway Cactus для увлажнения.\\nSiberian Wellness Chronolong для вечернего ухода.",'
            '"recommended_brands":["Greenway","Siberian Wellness"]}'
        )
        keyboard = care_result_keyboard("order-3", brands)
        self.assertEqual(len(keyboard.inline_keyboard[0]), 2)
        self.assertEqual(
            [button.url for button in keyboard.inline_keyboard[0]],
            [REF_LINK_GREENWAY, REF_LINK_SW],
        )

    def test_no_recommended_brands_means_no_referral_row(self):
        keyboard = care_result_keyboard("order-4", [])
        self.assertEqual(len(keyboard.inline_keyboard), 1)
        self.assertTrue(all(button.url is None for button in keyboard.inline_keyboard[0]))

    def test_negative_brand_mention_does_not_create_referral_button(self):
        _, brands = _parse_care_response(
            '{"answer":"Greenway не подходит при указанной непереносимости.",'
            '"recommended_brands":["Greenway"]}'
        )
        self.assertEqual(brands, [])
        self.assertEqual(len(care_result_keyboard("order-5", brands).inline_keyboard), 1)

    def test_malformed_or_missing_structured_response_never_adds_links(self):
        answer, brands = _parse_care_response("невалидный ответ Gemini")
        self.assertEqual(answer, "невалидный ответ Gemini")
        self.assertEqual(brands, [])
        _, brands = _parse_care_response('{"answer":"Только базовый уход"}')
        self.assertEqual(brands, [])

    def test_result_formatter_removes_markdown_asterisks(self):
        self.assertNotIn("*", _format_result("**Утро**\\n* очищение"))

    def test_existing_photo_and_quiz_prompts_keep_both_modes(self):
        self.assertIn("видимые особенности", _photo_prompt("корейский").lower())
        self.assertIn("Ответы пользователя", _quiz_prompt({"skin_type": "сухая"}))


if __name__ == "__main__":
    unittest.main()
