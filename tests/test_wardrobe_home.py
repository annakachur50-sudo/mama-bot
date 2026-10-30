import ast
import html
import re
import unittest
from pathlib import Path

SOURCE = Path("main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def load_wardrobe_helpers():
    wanted = {
        "wardrobe_is_home_occasion",
        "wardrobe_system_instruction",
        "wardrobe_palette_header",
        "wardrobe_result_html",
        "wardrobe_home_result_html",
    }
    functions = [
        node for node in TREE.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted
    ]
    constants = {"WARDROBE_STYLIST_PROMPT", "HOME_WARDROBE_INSTRUCTIONS", "HOME_TEMP_INSTRUCTIONS"}
    assignments = [
        node for node in TREE.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(isinstance(target, ast.Name) and target.id in constants for target in node.targets)
    ]
    namespace = {"re": re, "html": html}
    exec(compile(ast.Module(body=assignments, type_ignores=[]), "main.py", "exec"), namespace)
    exec(compile(ast.Module(body=functions, type_ignores=[]), "main.py", "exec"), namespace)
    return namespace


HELPERS = load_wardrobe_helpers()


class WardrobeHomeAndPaletteTests(unittest.TestCase):
    def test_saved_palette_has_only_the_short_individual_header(self):
        header = HELPERS["wardrobe_palette_header"](
            "Фотография: футболка бордового цвета; серёжки серебряные. Комплименты из анализа."
        )
        self.assertEqual(
            header,
            "🎨 <b>Подобрано по твоей индивидуальной палитре</b> ✨\n\n",
        )
        self.assertNotIn("футболка", header)
        self.assertNotIn("серёжки", header)
        self.assertNotIn("Комплименты", header)

    def test_missing_or_blank_palette_has_base_harmony_header(self):
        header = HELPERS["wardrobe_palette_header"](None)
        self.assertEqual(
            header,
            "🎨 <b>Подобрано в базовой гармоничной гамме</b> ✨\n\n",
        )
        self.assertEqual(
            HELPERS["wardrobe_palette_header"]("   "),
            "🎨 <b>Подобрано в базовой гармоничной гамме</b> ✨\n\n",
        )

    def test_home_occasion_is_detected_and_skips_outdoor_layer_step(self):
        is_home = HELPERS["wardrobe_is_home_occasion"]
        self.assertTrue(is_home("дома, но хочется выглядеть красиво"))
        self.assertTrue(is_home("Дома / Уютный день"))
        self.assertFalse(is_home("прогулка"))
        start = SOURCE.index("async def choose_wardrobe_occasion(")
        end = SOURCE.index('@dispatcher.callback_query(F.data == "wardrobe:back:occasion"', start)
        handler = SOURCE[start:end]
        home_branch = handler[handler.index("if is_home:"):handler.index("return", handler.index("if is_home:"))]
        self.assertIn("WardrobeStates.waiting_for_home_temp", home_branch)
        self.assertIn("Какая у тебя температура дома?", home_branch)
        self.assertNotIn("wardrobe_layer_keyboard()", home_branch)
        self.assertIn("await state.set_state(WardrobeStates.waiting_for_layer)", handler)

    def test_home_prompt_is_explicit_and_preserves_palette_context(self):
        prompt = HELPERS["wardrobe_system_instruction"](True)
        for phrase in (
            "исключительно для дома",
            "домашние костюмы",
            "платья",
            "лонгсливы",
            "тапочки/носочки",
            "кардиган/халат/рубашка",
            "Исключить уличную обувь, пальто, куртки и сумки",
            "Домашняя обувь / носочки",
        ):
            self.assertIn(phrase.casefold(), prompt.casefold())
        self.assertNotIn("Обувь и сумка:", prompt)
        generator_start = SOURCE.index("def generate_wardrobe_outfits_sync(")
        generator_end = SOURCE.index("\n\ndef radiance_menu_keyboard(", generator_start)
        generator = SOURCE[generator_start:generator_end]
        self.assertIn("if palette_context:", generator)
        self.assertIn("palette_context", generator)
        self.assertIn("wardrobe_system_instruction(is_home, home_temp)", generator)

    def test_home_card_replaces_outdoor_shoes_and_removes_bag_and_outerwear_rows(self):
        sample = (
            "<b>Комплект 1: Уютный</b>\n"
            "🔘 <b>Формула:</b> Футболка + Брюки + Кеды + Куртка + Сумка\n"
            "🎨 <b>Палитра:</b> ⚪ Молочный · 🟤 Бежевый\n"
            "• <b>Одежда:</b> Брюки + лонгслив\n"
            "• <b>Обувь и сумка:</b> Кеды + сумка\n"
            "• <b>Верхний слой:</b> Куртка\n"
            "• 💡 <b>Акцент:</b> Мягкая резинка\n\n"
            "<b>Комплект 2: Мягкий</b>\n"
            "• <b>Домашняя обувь / носочки:</b> Мягкие носочки\n"
            "• <b>Уютный слой:</b> Кардиган"
        )
        formatted = HELPERS["wardrobe_home_result_html"](sample)
        self.assertIn("Домашняя обувь / носочки", formatted)
        self.assertNotIn("сумка", formatted.casefold())
        self.assertNotIn("куртка", formatted.casefold())
        self.assertNotIn("кеды", formatted.casefold())
        self.assertNotIn("Верхний слой", formatted)
        self.assertIn("Палитра", formatted)
        self.assertIn("Формула", formatted)
        self.assertIn("Комплект 2", formatted)

    def test_other_scenarios_keep_the_existing_three_step_flow_and_card_format(self):
        self.assertIn('await state.set_state(WardrobeStates.waiting_for_layer)', SOURCE)
        self.assertIn('"Шаг 2 из 3: В чём идёшь / какой верхний слой? 🧥"', SOURCE)
        self.assertIn('callback_data="wardrobe:back:layer"', SOURCE)
        self.assertIn('• <b>Обувь и сумка:</b>', HELPERS["wardrobe_system_instruction"](False))
        ordinary = "<b>Комплект 1: Город</b>\n• <b>Обувь и сумка:</b> Ботинки + сумка"
        self.assertIn("Обувь и сумка", HELPERS["wardrobe_result_html"](ordinary))

    def test_back_navigation_and_new_scenario_clear_stale_parameters(self):
        self.assertIn('await state.set_data({})', SOURCE)
        self.assertIn('"wardrobe:back:occasion:home"', SOURCE)
        start = SOURCE.index("async def choose_wardrobe_occasion(")
        end = SOURCE.index('@dispatcher.callback_query(F.data == "wardrobe:back:occasion"', start)
        handler = SOURCE[start:end]
        self.assertIn("await state.set_data({", handler)
        self.assertIn('"base_item_is_custom": False', handler)
        self.assertIn("await state.clear()", SOURCE[SOURCE.index("async def start_wardrobe_flow("):SOURCE.index('@dispatcher.callback_query(F.data == "radiance:wardrobe:cancel"', SOURCE.index("async def start_wardrobe_flow("))])


if __name__ == "__main__":
    unittest.main()
