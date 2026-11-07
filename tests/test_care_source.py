import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from handlers_care import (CareStates, care_photo_category_keyboard, choose_care_mode, choose_care_photo_category, process_care_text)


class CareSourceSyntaxTests(unittest.TestCase):
    def test_care_module_parses(self):
        source = Path(__file__).resolve().parents[1] / "handlers_care.py"
        ast.parse(source.read_text(encoding="utf-8"), filename=str(source))

    def test_main_and_payment_modules_parse(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("main.py", "payments.py"):
            source = root / name
            with self.subTest(module=name):
                ast.parse(source.read_text(encoding="utf-8"), filename=str(source))

    def test_vision_uses_jpeg_bytes_and_detailed_error_logging(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "handlers_care.py").read_text(encoding="utf-8")
        self.assertIn('types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")', source)
        self.assertIn('logger.exception("Care vision error: %s", error)', source)
        self.assertIn("timeout=125", source)

    def test_care_inline_step_messages_are_deleted_on_transitions(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "handlers_care.py").read_text(encoding="utf-8")
        self.assertIn("async def _delete_callback_message(callback: CallbackQuery)", source)
        self.assertGreaterEqual(source.count("await _delete_callback_message(callback)"), 5)
        self.assertIn("await callback.message.delete()", source)
        self.assertIn("await send_care_result(callback.message", source)

    def test_photo_category_callback_data_stays_within_telegram_limit(self):
        keyboard = care_photo_category_keyboard("123e4567-e89b-12d3-a456-426614174000")
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertTrue(callback_data)
        self.assertLessEqual(max(len(value.encode("utf-8")) for value in callback_data), 64)
        self.assertIn("care:photo_category:p:123e4567-e89b-12d3-a456-426614174000", callback_data)

    def test_photo_consent_is_persisted_per_user_and_reused(self):
        root = Path(__file__).resolve().parents[1]
        handlers = (root / "handlers_care.py").read_text(encoding="utf-8")
        payments = (root / "payments.py").read_text(encoding="utf-8")
        self.assertIn("has_care_photo_consent_sync", handlers)
        self.assertIn("CareStates.waiting_for_photo_category", handlers)
        self.assertIn("has_care_photo_consent BOOLEAN NOT NULL DEFAULT FALSE", payments)
        self.assertIn("SET has_care_photo_consent = TRUE", payments)

    def test_photo_prompt_includes_cosmetics_category_and_emoji_formatting(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "handlers_care.py").read_text(encoding="utf-8")
        self.assertIn("def _photo_prompt(cosmetics_category: str)", source)
        self.assertIn("photo_cosmetics_category", source)
        self.assertIn("Markdown-жирное выделение только для заголовков и названий этапов", source)
        self.assertNotIn("**Название шага:**", source)
        self.assertIn("разрешённой матрицы", source)

    def test_radiance_menu_has_general_beauty_space_intro_not_cosmetologist_flow(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "main.py").read_text(encoding="utf-8")
        self.assertIn("Твоё персональное пространство красоты и стиля", source)
        self.assertIn("без многочасовых сборов и лишних трат", source)
        self.assertIn("Определим твои лучшие природные оттенки", source)
        self.assertIn("Соберём гармоничный и удобный образ на день", source)
        self.assertIn("Подберём бережный пошаговый ритуал ухода за кожей", source)
        self.assertNotIn("Твой персональный AI-косметолог", source)

    def test_care_cosmetologist_intro_is_inside_care_mode_flow(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "handlers_care.py").read_text(encoding="utf-8")
        self.assertIn("Твой персональный AI-косметолог", source)
        self.assertIn("Выбери, как тебе комфортнее провести разбор:", source)
        self.assertIn('text="📸 По фото лица"', source)
        self.assertIn('text="📝 По быстрым вопросам"', source)
        self.assertIn('text="⬅️ Назад в Сияние"', source)
        self.assertIn('callback_data="menu_radiance"', source)

    def test_care_prompts_enforce_morning_evening_and_product_rules(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "handlers_care.py").read_text(encoding="utf-8")
        rules_start = source.index("def _care_routine_rules")
        rules_end = source.index("def _photo_prompt", rules_start)
        rules = source[rules_start:rules_end]
        self.assertIn("Сухое очищение Sharme Minerals утром СТРОГО ЗАПРЕЩЕНО", rules)
        self.assertIn("ИСКЛЮЧИТЕЛЬНО вечером", rules)
        self.assertIn("2–3 раза в неделю", rules)
        self.assertIn("выбери ОДНО базовое средство", rules)
        self.assertIn("дневной крем-флюид Siberian Wellness Siberian Code", rules)
        self.assertIn("ниацинамид помогает регулировать себум", rules)
        self.assertIn("цинк помогает контролировать жирный блеск", rules)
        self.assertIn("гидролат календулы или берёзы", rules)
        photo_start = source.index("def _photo_prompt")
        quiz_start = source.index("def _quiz_prompt", photo_start)
        care_flow_start = source.index("@care_router.callback_query", quiz_start)
        photo_prompt = source[photo_start:quiz_start]
        quiz_prompt = source[quiz_start:care_flow_start]
        self.assertIn("_care_routine_rules(cosmetics_category)", photo_prompt)
        self.assertIn('_care_routine_rules(answers.get("brand_pref", ""))', quiz_prompt)

    def test_care_mode_intro_uses_html_parse_mode_on_entry_and_back(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "handlers_care.py").read_text(encoding="utf-8")
        entry_start = source.index("async def start_care_checkout")
        entry_end = source.index("async def send_care_result", entry_start)
        entry = source[entry_start:entry_end]
        self.assertIn("CARE_MODE_INTRO_TEXT", entry)
        self.assertIn('parse_mode="HTML"', entry)
        back_start = source.index("async def back_to_care_mode")
        back_end = source.index("@care_router.callback_query", back_start + 1)
        back = source[back_start:back_end]
        self.assertIn("CARE_MODE_INTRO_TEXT", back)
        self.assertIn('parse_mode="HTML"', back)

    def test_photo_mode_acknowledges_callback_before_database_checks(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "handlers_care.py").read_text(encoding="utf-8")
        start = source.index("async def choose_care_mode")
        end = source.index("@care_router.callback_query", start + 1)
        handler = source[start:end]
        self.assertLess(handler.index("await callback.answer()"), handler.index("has_care_access_sync"))

    def test_photo_instruction_keeps_photo_state_and_is_not_deleted(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "handlers_care.py").read_text(encoding="utf-8")
        start = source.index("async def choose_care_photo_category")
        end = source.index("@care_router.callback_query", start + 1)
        handler = source[start:end]
        self.assertIn("await state.set_state(CareStates.waiting_for_photo)", handler)
        self.assertIn("Пришли мне одно чёткое селфи", handler)
        self.assertLess(handler.index("await _delete_callback_message(callback)"),
                        handler.index("Пришли мне одно чёткое селфи"))

    def test_photo_handler_shows_typing_and_sends_jpeg_bytes(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "handlers_care.py").read_text(encoding="utf-8")
        start = source.index("async def process_care_photo")
        end = source.index("async def process_care_text", start)
        handler = source[start:end]
        helper_start = source.index("async def _analyze_care_photo_file")
        helper_end = source.index("async def process_care_photo", helper_start)
        photo_helper = source[helper_start:helper_end]
        self.assertIn('action="typing"', photo_helper)
        self.assertIn("await send_care_result(", photo_helper)
        self.assertIn("last_photo_file_id=file_id", photo_helper)
        self.assertIn("CareStates.waiting_for_photo.state", handler)
        self.assertIn('types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")', source)

    def test_photo_cache_is_stored_only_after_successful_analysis(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "handlers_care.py").read_text(encoding="utf-8")
        start = source.index("async def _analyze_care_photo_file")
        end = source.index("async def process_care_photo", start)
        helper = source[start:end]
        self.assertLess(helper.index("if success:"), helper.index("last_photo_file_id=file_id"))
        self.assertIn("await state.set_state(None)", helper)
        self.assertIn("care:photo_source:same", source)
        self.assertIn("care:photo_source:new", source)

    def test_shared_gemini_http_timeout_and_care_model_fallback(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "main.py").read_text(encoding="utf-8")
        self.assertIn('"timeout": 120000', source)
        self.assertIn('os.getenv("CARE_GEMINI_MODEL", GEMINI_MODEL)', source)


class CarePhotoFlowRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_photo_mode_keeps_menu_until_consent_is_ready_and_sends_next_step(self):
        callback = SimpleNamespace(
            data="care:mode:photo:order-123",
            from_user=SimpleNamespace(id=777),
            message=SimpleNamespace(
                answer=AsyncMock(),
                delete=AsyncMock(),
            ),
            answer=AsyncMock(),
        )
        state = SimpleNamespace(
            clear=AsyncMock(),
            update_data=AsyncMock(),
            set_state=AsyncMock(),
        )
        order = {"status": "succeeded", "mode": "photo"}

        with patch(
            "handlers_care.asyncio.to_thread",
            new=AsyncMock(side_effect=[True, order, True, True, True]),
        ):
            await choose_care_mode(callback, state)

        callback.answer.assert_awaited_once_with()
        callback.message.delete.assert_awaited_once_with()
        state.set_state.assert_awaited_once_with(CareStates.waiting_for_photo_category)
        callback.message.answer.assert_awaited_once()
        self.assertIn("Какому уходу отдаёшь предпочтение", callback.message.answer.await_args.args[0])

    async def test_care_photo_category_callback_sends_persistent_selfie_invitation(self):
        callback = SimpleNamespace(
            data="care:photo_category:n:order-123",
            from_user=SimpleNamespace(id=777),
            message=SimpleNamespace(
                answer=AsyncMock(),
                delete=AsyncMock(),
            ),
            answer=AsyncMock(),
        )
        state = SimpleNamespace(
            update_data=AsyncMock(),
            get_data=AsyncMock(return_value={}),
            set_state=AsyncMock(),
        )

        with patch("handlers_care.asyncio.to_thread", new=AsyncMock(side_effect=[True, True, True])):
            await choose_care_photo_category(callback, state)

        callback.answer.assert_awaited_once_with()
        state.set_state.assert_awaited_once_with(CareStates.waiting_for_photo)
        callback.message.delete.assert_awaited_once_with()
        callback.message.answer.assert_awaited_once()
        sent_text = callback.message.answer.await_args.args[0]
        self.assertIn("Пришли мне одно чёткое селфи", sent_text)
        self.assertIn("дневном свете", sent_text)
        self.assertIn("текстуру пор", sent_text)
        self.assertEqual(callback.message.answer.await_args.kwargs.get("parse_mode"), "HTML")

    async def test_care_photo_category_with_cached_photo_offers_reuse_or_new(self):
        callback = SimpleNamespace(
            data="care:photo_category:k:order-123",
            from_user=SimpleNamespace(id=777),
            message=SimpleNamespace(answer=AsyncMock(), delete=AsyncMock()),
            answer=AsyncMock(),
        )
        state = SimpleNamespace(
            update_data=AsyncMock(),
            get_data=AsyncMock(return_value={"last_photo_file_id": "telegram-file-123"}),
            set_state=AsyncMock(),
        )
        with patch("handlers_care.asyncio.to_thread", new=AsyncMock(side_effect=[True, True, True])):
            await choose_care_photo_category(callback, state)
        state.set_state.assert_awaited_once_with(CareStates.waiting_for_photo_source)
        kwargs = callback.message.answer.await_args.kwargs
        self.assertIsNotNone(kwargs.get("reply_markup"))
        texts = [
            button.text
            for row in kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("📸 Оставить то же фото", texts)
        self.assertIn("🔄 Загрузить новое селфи", texts)

    async def test_main_registers_photo_handler_for_waiting_for_photo_state(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "main.py").read_text(encoding="utf-8")
        self.assertIn("@dispatcher.message(CareStates.waiting_for_photo, F.photo)", source)
        self.assertIn("await process_care_photo(message, state)", source)

    async def test_text_and_voice_like_non_photo_inputs_keep_waiting_state(self):
        for kind in ("text", "voice"):
            state = SimpleNamespace(
                get_state=AsyncMock(return_value=CareStates.waiting_for_photo.state),
                get_data=AsyncMock(return_value={"order_id": "order-123"}),
            )
            message = SimpleNamespace(answer=AsyncMock())
            handled = await process_care_text(message, state)
            self.assertTrue(handled, kind)
            self.assertIn("Пожалуйста, отправь именно фотографию лица", message.answer.await_args.args[0])
            state.get_state.assert_awaited_once_with()

    async def test_main_registers_non_photo_catch_all_for_selfie_state(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "main.py").read_text(encoding="utf-8")
        self.assertIn("@dispatcher.message(CareStates.waiting_for_photo, ~F.photo)", source)
        self.assertIn("async def reject_non_photo_care_message", source)

    async def test_photo_analysis_uses_visible_skin_texture_status(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "handlers_care.py").read_text(encoding="utf-8")
        self.assertIn('"Изучаю текстуру кожи... ✨" if image_bytes is not None', source)
        self.assertIn('types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")', source)

    def test_radiance_entry_shows_general_beauty_space_welcome(self):
        root = Path(__file__).resolve().parents[1]
        main = (root / "main.py").read_text(encoding="utf-8")
        care = (root / "handlers_care.py").read_text(encoding="utf-8")
        welcome = main[main.index("RADIANCE_MENU_TEXT"):main.index("WARDROBE_STYLIST_PROMPT")]
        self.assertIn("Твоё персональное пространство красоты и стиля", welcome)
        self.assertIn("Выбирай, с чего начнём:", welcome)
        self.assertIn("Определим твои лучшие природные оттенки", welcome)
        self.assertIn("Соберём гармоничный и удобный образ на день", welcome)
        self.assertIn("Подберём бережный пошаговый ритуал ухода за кожей", welcome)
        self.assertNotIn("AI-косметолог", welcome)
        self.assertIn('callback_data="care:open"', main)
        self.assertIn("async def open_care_from_menu", care)


if __name__ == "__main__":
    unittest.main()
