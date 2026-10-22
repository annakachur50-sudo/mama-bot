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
        self.assertIn("result = await kids_activity_for_age(selected_age, user_id)", SOURCE)
        self.assertIn('int(age["child_number"]) == child_number', SOURCE)
        self.assertIn("ages = await asyncio.to_thread(load_family_ages, user_id)", SOURCE)

    def test_joint_prompt_includes_every_participant(self):
        self.assertIn("asyncio.to_thread(generate_kids_activity_sync, ages, previous)", SOURCE)
        self.assertIn("для всех перечисленных возрастов", SOURCE)
        self.assertIn("разные роли", SOURCE)
        self.assertIn("или уровни сложности", SOURCE)

    def test_teen_prompt_excludes_childish_games_by_default(self):
        self.assertIn("Для любого участника 13–17 лет не предлагай примитивные детские игры", SOURCE)
        self.assertIn("если подросток сам этого не попросил", SOURCE)

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
        self.assertIn("ТОЛЬКО на конкретные детали, отчётливо видимые", prompt)
        self.assertIn("не придумывай улыбку, чёлку, макияж", prompt)
        self.assertIn("не угадывай", prompt)
        self.assertIn("4–5 понятных оттенков", prompt)
        self.assertIn("1–2 оттенка", prompt)
        self.assertIn("Не повторяй предупреждение о дневном свете", prompt)

    def test_selfie_waiting_copy_is_exact_and_single_source(self):
        self.assertIn(
            "Сделай или отправь своё любимое селфи при дневном свете у окна (без фильтров и масок) 🌸",
            SOURCE,
        )
        self.assertIn(
            "А я помогу раскрыть твои природные краски и подберу цвета, которые подчеркнут твою естественную красоту! ✨",
            SOURCE,
        )
        self.assertEqual(SOURCE.count("Сделай или отправь своё любимое селфи"), 1)

    def test_kids_prompt_addresses_adult_and_requires_scannable_format(self):
        start = SOURCE.index("def generate_kids_activity_sync(")
        end = SOURCE.index("\n\nasync def kids_activity_for_age(", start)
        prompt = SOURCE[start:end]
        self.assertIn("ответ именно взрослому, а не ребёнку", prompt)
        self.assertIn("читаться по диагонали за 5 секунд", prompt)
        self.assertIn("короткий интересный заголовок", prompt)
        self.assertIn("мама может сразу произнести или переслать ребёнку", prompt)
        self.assertIn("обязательно заключи эту реплику в «ёлочки»", prompt)
        self.assertIn("Не используй Markdown или HTML-теги", prompt)
        self.assertIn("Для подростка 13–15 лет", prompt)
        self.assertIn("детективная загадка с логичной разгадкой", prompt)
        self.assertIn("Не предлагай малышовые игры по умолчанию", prompt)

    def test_game_result_navigation_is_profile_backed(self):
        self.assertIn('callback_data="kids:again:all" if joint else f"kids:again:{current_child_number}"', SOURCE)
        self.assertIn('callback_data=f"kids:child:{child_number}"', SOURCE)
        self.assertIn('text="🤝 Игра для всех"', SOURCE)
        self.assertIn('text="🏠 В главное меню"', SOURCE)
        self.assertIn("ages = await asyncio.to_thread(load_family_ages, user_id)", SOURCE)
        self.assertIn("kids_generation_in_progress", SOURCE)
        self.assertIn("if user_id in kids_generation_in_progress", SOURCE)

    def test_game_html_formatter_escapes_text_and_uses_real_newlines(self):
        formatter_node = next(
            node for node in TREE.body
            if isinstance(node, ast.FunctionDef) and node.name == "format_kids_activity_html"
        )
        namespace = {"html": __import__("html"), "re": __import__("re")}
        exec(compile(ast.Module(body=[formatter_node], type_ignores=[]), "main.py", "exec"), namespace)
        result = namespace["format_kids_activity_html"](
            "🕵️ «Секретный агент» (7 лет)\nПредложи игру.\nСкажи: «Найди подсказку <в комнате>».",
            "7 лет",
        )
        self.assertTrue(result.startswith("<b>🕵️ «Секретный агент» (7 лет)</b>"))
        self.assertIn("\n", result)
        self.assertNotIn("\\n", result)
        self.assertIn("«<b>Найди подсказку &lt;в комнате&gt;</b>»", result)
        self.assertNotIn("<в комнате>", result)

    def test_game_html_is_escaped_before_controlled_formatting(self):
        start = SOURCE.index("def format_kids_activity_html(")
        end = SOURCE.index("\n\ndef generate_kids_activity_sync(", start)
        formatter = SOURCE[start:end]
        self.assertIn("html.escape(line, quote=False)", formatter)
        self.assertIn('escaped_lines[0] = f"<b>{escaped_lines[0]}</b>"', formatter)
        self.assertIn("«<b>", formatter)

    def test_radiance_result_has_retry_and_home_navigation(self):
        self.assertIn('text="🔄 Попробовать другое фото"', SOURCE)
        self.assertIn('callback_data="radiance:retry"', SOURCE)
        self.assertIn("await start_radiance_selfie(callback.message, callback.from_user.id)", SOURCE)
        self.assertIn("reply_markup=radiance_result_keyboard()", SOURCE)

    def test_16_plus_uses_senior_teen_label(self):
        label = HELPERS["kids_picker_label"]
        self.assertEqual(label(age(16)), "✨ Старший подросток")
        self.assertEqual(label(age(18)), "✨ Старший подросток")


if __name__ == "__main__":
    unittest.main()
