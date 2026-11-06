import ast
import unittest
from pathlib import Path


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
        self.assertIn("без markdown-маркеров списков", source)
        self.assertIn("Запрещено использовать списки со звёздочками", source)

    def test_care_intro_is_cosmetologist_not_old_stylist_placeholder(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "main.py").read_text(encoding="utf-8")
        self.assertIn("Твой персональный AI-косметолог", source)
        self.assertIn("Каждая мама заслуживает сиять", source)
        self.assertNotIn("Твой личный AI-стилист и бьюти-помощник", source)

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
        self.assertIn('action="typing"', handler)
        self.assertIn("await send_care_result(message", handler)
        self.assertIn("CareStates.waiting_for_photo.state", handler)
        self.assertIn('types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")', source)

    def test_shared_gemini_http_timeout_and_care_model_fallback(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "main.py").read_text(encoding="utf-8")
        self.assertIn('"timeout": 120000', source)
        self.assertIn('os.getenv("CARE_GEMINI_MODEL", GEMINI_MODEL)', source)


if __name__ == "__main__":
    unittest.main()
