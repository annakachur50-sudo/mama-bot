import ast
import re
import unittest
from pathlib import Path

SOURCE = Path("main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def extract(name):
    return next(
        node for node in TREE.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )


def load_temperature_helpers():
    assignments = [
        node for node in TREE.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id in {"HOME_TEMP_INSTRUCTIONS", "HOME_WARDROBE_INSTRUCTIONS", "WARDROBE_STYLIST_PROMPT"}
            for target in node.targets
        )
    ]
    functions = [
        extract("wardrobe_system_instruction"),
        extract("wardrobe_is_home_occasion"),
    ]
    namespace = {"re": re}
    exec(compile(ast.Module(body=assignments + functions, type_ignores=[]), "main.py", "exec"), namespace)
    return namespace


HELPERS = load_temperature_helpers()


class HomeWardrobeTemperatureTests(unittest.TestCase):
    def test_home_occasion_opens_temperature_choice_before_base_item(self):
        self.assertIn("Какая у тебя температура дома?", SOURCE)
        self.assertIn('callback_data="wardrobe:home_temp:warm"', SOURCE)
        self.assertIn('callback_data="wardrobe:home_temp:cool"', SOURCE)
        self.assertIn("WardrobeStates.waiting_for_home_temp", SOURCE)
        self.assertIn("reply_markup=wardrobe_home_temp_keyboard()", SOURCE)

    def test_warm_temperature_instruction_restricts_fabrics_and_layers(self):
        prompt = HELPERS["wardrobe_system_instruction"](True, "warm")
        for phrase in ("однослойный образ", "хлопковая футболка", "никакого второго слоя", "не добавляй строку", "босиком", "открытые шлёпанцы", "никаких носков", "не предлагай украшения", "крабиком", "мягкой/шёлковой резинкой"):
            self.assertIn(phrase, prompt)

    def test_cool_temperature_instruction_requires_cozy_layers(self):
        prompt = HELPERS["wardrobe_system_instruction"](True, "cool")
        for phrase in ("мягкий трикотажный костюм", "лонгслив", "свободные брюки", "мягкий кардиган", "тёплые носочки", "закрытые домашние тапочки"):
            self.assertIn(phrase, prompt)

    def test_selected_temperature_is_saved_and_passed_to_every_generation(self):
        self.assertIn("home_temp=home_temp", SOURCE)
        self.assertIn("HOME_TEMP_INSTRUCTIONS[home_temp]", SOURCE)
        self.assertIn('layer = "без второго слоя" if home_temp == "warm"', SOURCE)
        self.assertIn('home_temp == "warm"', SOURCE)
        self.assertIn("wardrobe_home_result_html(result, home_temp)", SOURCE)
        self.assertIn("generate_wardrobe_outfits_sync", SOURCE)
        self.assertIn("home_temp,", SOURCE)
        self.assertIn('callback_data="radiance:wardrobe:repeat"', SOURCE)
        self.assertIn('data["base_item"]', SOURCE)

    def test_back_from_base_returns_to_temperature_without_clearing_it(self):
        start = SOURCE.index("async def wardrobe_home_back_to_temp")
        end = SOURCE.index("@dispatcher.callback_query(F.data.startswith", start)
        handler = SOURCE[start:end]
        self.assertIn("WardrobeStates.waiting_for_home_temp", handler)
        self.assertNotIn("set_data", handler)
        self.assertIn("wardrobe_home_temp_keyboard()", handler)

    def test_back_from_temperature_clears_only_home_specific_values(self):
        start = SOURCE.index("async def wardrobe_home_temp_back_to_occasion")
        end = SOURCE.index("@dispatcher.callback_query(F.data.startswith", start)
        handler = SOURCE[start:end]
        self.assertIn('"home_temp", "layer", "base_item_is_custom"', handler)
        self.assertIn("WardrobeStates.waiting_for_occasion", handler)

    def test_other_scenarios_keep_their_existing_layer_step(self):
        self.assertIn("await state.set_state(WardrobeStates.waiting_for_layer)", SOURCE)
        self.assertIn("reply_markup=wardrobe_layer_keyboard()", SOURCE)
        self.assertEqual(HELPERS["wardrobe_system_instruction"](False), HELPERS["WARDROBE_STYLIST_PROMPT"])

    def test_home_generation_excludes_streetwear_and_keeps_palette(self):
        self.assertIn("palette_instruction", SOURCE)
        self.assertIn("Исключить уличную обувь, пальто, куртки и сумки", SOURCE)
        self.assertIn("Температурный режим дома:", SOURCE)


if __name__ == "__main__":
    unittest.main()
