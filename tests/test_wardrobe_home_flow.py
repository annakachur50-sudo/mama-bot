import ast
import re
import unittest
from pathlib import Path

SOURCE = Path("main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def load_wardrobe_helpers():
    wanted_functions = {
        "wardrobe_is_home_occasion",
        "wardrobe_system_instruction",
        "wardrobe_palette_header",
    }
    nodes = [
        node for node in TREE.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in wanted_functions
    ]
    wanted_assignments = {"HOME_WARDROBE_INSTRUCTIONS", "WARDROBE_STYLIST_PROMPT", "HOME_TEMP_INSTRUCTIONS"}
    assignments = [
        node for node in TREE.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id in wanted_assignments for target in node.targets)
    ]
    namespace = {"re": re}
    exec(compile(ast.Module(body=assignments, type_ignores=[]), "main.py", "exec"), namespace)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "main.py", "exec"), namespace)
    return namespace


HELPERS = load_wardrobe_helpers()


class WardrobeHomeFlowTests(unittest.TestCase):
    def test_saved_analysis_gets_only_exact_individual_palette_header(self):
        header = HELPERS["wardrobe_palette_header"](
            "Анализ: ты прекрасно выглядишь; футболка синяя, серьги серебряные."
        )
        self.assertEqual(
            header,
            "🎨 <b>Подобрано по твоей индивидуальной палитре</b> ✨\n\n",
        )
        self.assertNotIn("футболка", header)
        self.assertNotIn("серьги", header)
        self.assertNotIn("прекрасно", header)

    def test_missing_analysis_gets_only_exact_basic_palette_header(self):
        header_fn = HELPERS["wardrobe_palette_header"]
        expected = "🎨 <b>Подобрано в базовой гармоничной гамме</b> ✨\n\n"
        self.assertEqual(header_fn(None), expected)
        self.assertEqual(header_fn("  "), expected)

    def test_home_occasion_is_detected_and_skips_street_layer_step(self):
        self.assertTrue(HELPERS["wardrobe_is_home_occasion"]("дома, но хочется выглядеть красиво"))
        self.assertTrue(HELPERS["wardrobe_is_home_occasion"]("Домашний уютный день"))
        self.assertFalse(HELPERS["wardrobe_is_home_occasion"]("прогулка"))
        self.assertIn('if is_home:', SOURCE)
        self.assertIn('await state.set_state(WardrobeStates.waiting_for_home_temp)', SOURCE)
        self.assertIn('reply_markup=wardrobe_home_temp_keyboard()', SOURCE)
        self.assertIn('await state.set_state(WardrobeStates.waiting_for_layer)', SOURCE)

    def test_home_prompt_has_required_clothes_and_excludes_street_items(self):
        prompt = HELPERS["wardrobe_system_instruction"](True)
        for phrase in (
            "исключительно для дома",
            "домашние костюмы",
            "платья",
            "лонгсливы",
            "тапочки/носочки",
            "кардиган/халат/рубашка",
            "Исключить уличную обувь, пальто, куртки и сумки",
        ):
            self.assertIn(phrase, prompt)
        self.assertNotIn("Обувь и сумка:", prompt)

    def test_home_request_passes_palette_and_does_not_use_street_parameters(self):
        start = SOURCE.index("async def generate_wardrobe_result(")
        end = SOURCE.index('@dispatcher.callback_query(F.data.startswith("wardrobe:base:")', start)
        handler = SOURCE[start:end]
        self.assertIn("is_home = wardrobe_is_home_occasion(occasion)", handler)
        self.assertIn("generate_wardrobe_outfits_sync", handler)
        self.assertIn("is_home,", handler)
        self.assertIn("palette_instruction", handler)
        self.assertIn("Сценарий: дома / уютный день", handler)
        self.assertIn("Исключить уличную обувь, пальто, куртки и сумки", handler)

    def test_home_card_format_uses_home_footwear_and_no_bag(self):
        prompt = HELPERS["wardrobe_system_instruction"](True)
        self.assertIn("Домашняя обувь / носочки", prompt)
        self.assertNotIn("Обувь и сумка", prompt)
        self.assertNotIn("Верхний слой:</b> [Куртка/пальто/тренч", prompt)
        self.assertIn("Формула:", prompt)
        self.assertIn("Палитра:", prompt)

    def test_non_home_flow_and_card_template_remain_unchanged(self):
        self.assertEqual(
            HELPERS["wardrobe_system_instruction"](False),
            HELPERS["WARDROBE_STYLIST_PROMPT"],
        )
        self.assertIn('await state.set_state(WardrobeStates.waiting_for_layer)', SOURCE)
        self.assertIn('reply_markup=wardrobe_layer_keyboard()', SOURCE)
        self.assertIn('• <b>Обувь и сумка:</b> [Удобная обувь + сумка/рюкзак]', SOURCE)
        self.assertIn('• <b>Верхний слой:</b> [Куртка/пальто/тренч, соответствующие выбранному слою]', SOURCE)

    def test_back_and_restart_clear_stale_wardrobe_parameters(self):
        self.assertIn('await state.clear()\n    await state.set_state(WardrobeStates.waiting_for_occasion)', SOURCE)
        self.assertIn('await state.set_data({\n        "occasion": occasions[occasion_key],\n        "base_item_is_custom": False,\n    })', SOURCE)
        self.assertIn('async def wardrobe_home_temp_back_to_occasion', SOURCE)
        home_back_start = SOURCE.index("async def wardrobe_home_temp_back_to_occasion")
        home_back_end = SOURCE.index('@dispatcher.callback_query(F.data.startswith("wardrobe:home_temp:")', home_back_start)
        self.assertIn('"home_temp", "layer", "base_item_is_custom"', SOURCE[home_back_start:home_back_end])
        self.assertIn('finally:\n        await state.clear()', SOURCE)


if __name__ == "__main__":
    unittest.main()
