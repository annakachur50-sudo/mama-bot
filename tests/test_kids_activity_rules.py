import ast
import unittest
from pathlib import Path

SOURCE = Path("main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def load_helpers():
    wanted = {
        "kids_age_months", "kids_age_band", "kids_picker_label",
        "kids_activity_context_key", "kids_activity_short_id", "kids_next_activity_category",
        "kids_activity_is_duplicate", "kids_activity_fallback", "format_child_age",
    }
    nodes = [node for node in TREE.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted]
    needed_assignments = {"KIDS_ACTIVITY_CATEGORIES", "KIDS_ACTIVITY_POOLS", "KIDS_TEEN_FALLBACKS"}
    assignments = [
        node for node in TREE.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id in needed_assignments for target in node.targets)
    ]
    namespace = {
        "kids_last_categories": {},
        "random": __import__("random"),
        "re": __import__("re"),
        "html": __import__("html"),
    }
    exec(compile(ast.Module(body=assignments, type_ignores=[]), "main.py", "exec"), namespace)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "main.py", "exec"), namespace)
    return namespace


HELPERS = load_helpers()


def age(years):
    return {"child_number": 1, "age_value": years, "age_unit": "years"}


class KidsAgeRulesTests(unittest.TestCase):
    def test_age_bands_for_requested_samples(self):
        band = HELPERS["kids_age_band"]
        self.assertEqual(band(24)[0], "до 3 лет")
        self.assertEqual(band(35)[0], "до 3 лет")
        self.assertEqual(band(36)[0], "3–5 лет")
        self.assertEqual(band(60)[0], "3–5 лет")
        self.assertEqual(band(84)[0], "6–9 лет")
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
        self.assertIn("asyncio.to_thread(generate_kids_activity_sync, ages, previous, category)", SOURCE)
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

    def test_duplicate_detector_rejects_same_title_and_same_body(self):
        duplicate = HELPERS["kids_activity_is_duplicate"]
        self.assertTrue(duplicate(
            "🕵️ «Криминалистический парадокс» (14 лет)\nИдея одна и та же.",
            "🕵️ «Криминалистический парадокс» (14 лет)\nДругой текст.",
        ))
        self.assertTrue(duplicate(
            "🎨 «Новая обложка» (14 лет)\nПредложи сделать постер в трёх цветах.",
            "🎨 «Другой заголовок» (14 лет)\nПредложи сделать постер в трёх цветах.",
        ))
        self.assertFalse(duplicate(
            "🎨 «Новая обложка» (14 лет)\nПредложи сделать постер в трёх цветах.",
            "🎲 «Музыкальный баттл» (14 лет)\nВыберите трек и объясните свой выбор.",
        ))

    def test_fallback_rotation_excludes_the_previous_activity_for_each_age_band(self):
        fallback = HELPERS["kids_activity_fallback"]
        short_id = HELPERS["kids_activity_short_id"]
        samples = (
            {"child_number": 1, "age_value": 8, "age_unit": "months"},
            age(2), age(4), age(8), age(11), age(14), age(16), age(18),
        )
        for selected_age in samples:
            with self.subTest(age=selected_age):
                first = fallback(selected_age)
                second = fallback(selected_age, {short_id(first)})
                self.assertNotEqual(short_id(first), short_id(second))
                self.assertIn(f"({HELPERS['format_child_age'](selected_age)})", first.splitlines()[0])
                self.assertIn(f"({HELPERS['format_child_age'](selected_age)})", second.splitlines()[0])

    def test_live_generation_retries_duplicate_and_fallback_excludes_previous(self):
        start = SOURCE.index("def generate_kids_activity_sync(")
        end = SOURCE.index("\n\nasync def kids_activity_for_age(", start)
        generator = SOURCE[start:end]
        self.assertIn("kids_activity_is_duplicate(activity, previous)", generator)
        self.assertIn("last_error = \"повтор предыдущей идеи\"", generator)
        start = SOURCE.index("async def kids_activity_for_age(")
        end = SOURCE.index("\n\nasync def kids_joint_activity(", start)
        single = SOURCE[start:end]
        self.assertIn("kids_activity_fallback(age, excluded_ids=excluded)", single)
        self.assertNotIn('f"🎨 «Три цвета»', single)

    def test_radiance_status_precedes_vision_call_and_handles_result(self):
        handler_start = SOURCE.index("async def handle_admin_photo(")
        handler_end = SOURCE.index('@dispatcher.message(Command("testfoodphoto"))', handler_start)
        handler = SOURCE[handler_start:handler_end]
        self.assertIn("Секундочку, любуюсь твоим фото и подбираю идеальную палитру... ✨", handler)
        self.assertLess(handler.index("status_message = await message.answer("), handler.index("analyze_radiance_photo_sync"))
        self.assertIn("status_message.edit_text(", handler)
        self.assertIn("formatted_result", handler)
        self.assertIn("status_message.edit_text(error_text", handler)
        self.assertIn("await message.answer(error_text", handler)

    def test_radiance_prompt_is_plain_and_grounded(self):
        start = SOURCE.index("def analyze_radiance_photo_sync(")
        end = SOURCE.index("\n\nasync def start_kids_flow(", start)
        prompt = SOURCE[start:end]
        self.assertIn("ТОЛЬКО на конкретные детали, отчётливо видимые", prompt)
        self.assertIn("не придумывай улыбку, чёлку, макияж", prompt)
        self.assertIn("не угадывай", prompt.lower())
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
        for category in (
            "🧠 Подумать и разгадать", "🎨 Придумать и создать",
            "🎲 Поиграть и посмеяться", "🔎 Найти и исследовать",
            "🤝 Сделать вместе", "🌿 Спокойно переключиться",
        ):
            self.assertIn(category, SOURCE)
        self.assertIn("строго соблюдай выбранную категорию", prompt.lower())
        self.assertIn("не повторяй прошлую идею под новым названием", prompt.lower())

    def test_kids_category_cycles_and_state_is_per_child(self):
        self.assertIn("kids_last_categories: dict[tuple[int, str], str]", SOURCE)
        self.assertIn('return (user_id, f"child:{int(ages[0][\'child_number\'])}")', SOURCE)
        self.assertIn('return (user_id, "all")', SOURCE)
        self.assertIn("kids_activity_context_key(user_id, [age])", SOURCE)
        self.assertIn("kids_activity_context_key(user_id, ages, joint=True)", SOURCE)
        self.assertIn("generate_kids_activity_sync, [age], previous, category", SOURCE)
        self.assertIn("generate_kids_activity_sync, ages, previous, category", SOURCE)

        category_fn = HELPERS["kids_next_activity_category"]
        context_key = HELPERS["kids_activity_context_key"](42, [age(7)])
        first = category_fn(42, context_key[1], [age(7)])
        HELPERS["kids_last_categories"][context_key] = first[0]
        second = category_fn(42, context_key[1], [age(7)])
        self.assertNotEqual(first[0], second[0])
        self.assertEqual(
            second[0],
            HELPERS["KIDS_ACTIVITY_CATEGORIES"][
                (next(i for i, item in enumerate(HELPERS["KIDS_ACTIVITY_CATEGORIES"]) if item[0] == first[0]) + 1)
                % len(HELPERS["KIDS_ACTIVITY_CATEGORIES"])
            ][0],
        )

        toddler_first = category_fn(99, "child:1", [age(2)])
        HELPERS["kids_last_categories"][(99, "child:1")] = toddler_first[0]
        toddler_next = category_fn(99, "child:1", [age(2)])
        self.assertNotEqual(toddler_first[0], "think")
        self.assertNotEqual(toddler_next[0], "think")
        self.assertNotEqual(toddler_first[0], toddler_next[0])
        self.assertIn("kids_last_activity_ids: dict[tuple[int, str], str]", SOURCE)
        short_id = HELPERS["kids_activity_short_id"]
        self.assertEqual(short_id('🎨 «Фотоохота: найди треугольник» (7 лет)'), "фотоохота-найди-треугольник")
        self.assertIn("kids_last_activity_ids[context_key] = kids_activity_short_id(activity)", SOURCE)

    def test_age_specific_generation_preserves_selected_child_and_age(self):
        self.assertIn("format_child_age(age)", SOURCE)
        self.assertIn('int(age["child_number"]) == child_number', SOURCE)
        self.assertIn("selected_age, user_id", SOURCE)
        self.assertIn("ages = await asyncio.to_thread(load_family_ages, user_id)", SOURCE)

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
        self.assertIn('escaped_line = f"<b>{escaped_line}</b>"', formatter)
        self.assertIn("<tg-spoiler>{escaped_answer}</tg-spoiler>", formatter)
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

    def test_riddle_prompt_requires_one_grounded_answer_for_all_ages(self):
        start = SOURCE.index("def generate_kids_activity_sync(")
        end = SOURCE.index("\n\nasync def kids_activity_for_age(", start)
        prompt = SOURCE[start:end]
        self.assertIn("условие, в котором достаточно фактов для одного проверяемого ответа", prompt)
        self.assertIn("фактов без внешних предположений", prompt)
        self.assertIn("максимум 15 слов", prompt)
        self.assertIn("В отгадке запрещены слова и конструкции", prompt)
        self.assertIn("Перед ответом проверь логическую согласованность", prompt)
        self.assertIn("Для занятия без загадки или логической задачи отгадку НЕ добавляй", prompt)

    def test_spoiler_answer_escapes_html_sensitive_characters(self):
        formatter_node = next(
            node for node in TREE.body
            if isinstance(node, ast.FunctionDef) and node.name == "format_kids_activity_html"
        )
        namespace = {"html": __import__("html"), "re": __import__("re")}
        exec(compile(ast.Module(body=[formatter_node], type_ignores=[]), "main.py", "exec"), namespace)
        result = namespace["format_kids_activity_html"](
            '🕵️ «Дело о знаках» (14 лет)\nКто оставил записку?\n'
            '💡 Отгадка для мамы: знак <А> & "Б" > 2',
            "14 лет",
        )
        self.assertIn(
            '<tg-spoiler>знак &lt;А&gt; &amp; "Б" &gt; 2</tg-spoiler>',
            result,
        )
        self.assertEqual(result.count("<tg-spoiler>"), 1)

    def test_teen_danetka_and_joint_family_game_keep_spoiler_at_the_end(self):
        formatter_node = next(
            node for node in TREE.body
            if isinstance(node, ast.FunctionDef) and node.name == "format_kids_activity_html"
        )
        namespace = {"html": __import__("html"), "re": __import__("re")}
        exec(compile(ast.Module(body=[formatter_node], type_ignores=[]), "main.py", "exec"), namespace)
        samples = [
            (
                "🕵️ «Ночной звонок» (14 лет)\nГерой услышал звонок, но телефон не звонил. Почему?\n"
                "💡 Отгадка для мамы: звонок шёл с другого устройства.",
                "14 лет",
            ),
            (
                "🤝 «Семейный детектив» (5, 9 и 14 лет)\nВсе вместе ищут одну улику.\n"
                "💡 Отгадка для мамы: записка лежит под синей книгой.",
                "5, 9 и 14 лет",
            ),
        ]
        for sample, ages_caption in samples:
            with self.subTest(ages=ages_caption):
                result = namespace["format_kids_activity_html"](sample, ages_caption)
                self.assertEqual(result.count("<tg-spoiler>"), 1)
                self.assertEqual(result.count("</tg-spoiler>"), 1)
                self.assertLess(result.index("Все вместе") if "Все вместе" in result else 0, result.index("<tg-spoiler>"))
                self.assertTrue(result.endswith("</tg-spoiler>"))

    def test_non_riddle_activity_does_not_gain_spoiler(self):
        formatter_node = next(
            node for node in TREE.body
            if isinstance(node, ast.FunctionDef) and node.name == "format_kids_activity_html"
        )
        namespace = {"html": __import__("html"), "re": __import__("re")}
        exec(compile(ast.Module(body=[formatter_node], type_ignores=[]), "main.py", "exec"), namespace)
        result = namespace["format_kids_activity_html"](
            '🎨 «Три цвета» (7 лет)\nНарисуйте необычный дом тремя цветами.',
            "7 лет",
        )
        self.assertNotIn("<tg-spoiler>", result)
        self.assertIn("Нарисуйте необычный дом", result)

    def test_kids_messages_use_html_parse_mode_and_controlled_spoiler(self):
        self.assertIn("parse_mode=ParseMode.HTML", SOURCE)
        start = SOURCE.index("def format_kids_activity_html(")
        end = SOURCE.index("\n\ndef generate_kids_activity_sync(", start)
        formatter = SOURCE[start:end]
        self.assertIn("html.escape(answer, quote=False)", formatter)
        self.assertIn("<tg-spoiler>{escaped_answer}</tg-spoiler>", formatter)
        self.assertIn("answer_match", formatter)


    def test_answer_validator_accepts_one_short_grounded_sentence(self):
        validator = self._load_answer_validator()
        self.assertIsNone(validator(
            "🕵️ «Дело о свете» (12 лет)\nЛампа горела в полночь.\n"
            "💡 Отгадка для мамы: Во всём районе в полночь отключили электричество, поэтому лампа не могла гореть."
        ))
        self.assertIsNone(validator(
            "🕵️ «Звонок из комнаты» (14 лет)\nТелефон героя выключен, но он слышит звонок из соседней комнаты. Что звонило?\n"
            "💡 Отгадка для мамы: В соседней комнате звонил будильник, а телефон героя был выключен."
        ))

    def test_answer_validator_rejects_ambiguous_or_speculative_answer(self):
        validator = self._load_answer_validator()
        samples = [
            "💡 Отгадка для мамы: Он ушёл домой или остался в школе.",
            "💡 Отгадка для мамы: Бизнесмен утверждал, что читал в полночь, хотя точнее в классической задаче электричество отключили или было темно.",
            "💡 Отгадка для мамы: Возможно, лампа работала от батарейки.",
            "💡 Отгадка для мамы: В классической задаче ответ — фонарь.",
            "💡 Отгадка для мамы: Он пришёл. Потом ушёл.",
            "💡 Отгадка для мамы: Это был человек, который пришёл ночью, увидел свет и решил, что кто-то дома вместе с соседями.",
            "💡 Отгадка для мамы: Это была батарейка (или запасной генератор).",
        ]
        for answer in samples:
            with self.subTest(answer=answer):
                self.assertIsNotNone(validator("🕵️ «Проверка» (12 лет)\nКто это сделал?\n" + answer))

    def test_riddle_without_answer_is_rejected_but_non_riddle_is_allowed(self):
        validator = self._load_answer_validator()
        self.assertIsNotNone(validator("🕵️ «Тайна» (12 лет)\nДетектив ищет улику."))
        self.assertIsNone(validator("🎨 «Три цвета» (7 лет)\nНарисуйте дом тремя цветами."))

    def test_answer_validator_checks_only_answer_not_riddle_condition(self):
        validator = self._load_answer_validator()
        self.assertIsNone(validator(
            "🕵️ «Выбор» (12 лет)\nВ условии есть слово «или»: что произошло?\n"
            "💡 Отгадка для мамы: Виновник оставил записку на столе."
        ))

    def _load_answer_validator(self):
        wanted = {node.name for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "KidsActivityValidationError"}
        wanted |= {node.name for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name == "kids_activity_answer_error"}
        nodes = [node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name in wanted]
        nodes += [node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
        namespace = {"re": __import__("re")}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "main.py", "exec"), namespace)
        return namespace["kids_activity_answer_error"]

if __name__ == "__main__":
    unittest.main()
