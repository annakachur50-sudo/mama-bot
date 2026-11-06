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

    def test_shared_gemini_http_timeout_and_care_model_fallback(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "main.py").read_text(encoding="utf-8")
        self.assertIn('"timeout": 120000', source)
        self.assertIn('os.getenv("CARE_GEMINI_MODEL", GEMINI_MODEL)', source)


if __name__ == "__main__":
    unittest.main()

    def test_vision_uses_jpeg_bytes_and_detailed_error_logging(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "handlers_care.py").read_text(encoding="utf-8")
        self.assertIn('types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")', source)
        self.assertIn('logger.exception("Care vision error: %s", error)', source)
        self.assertIn("timeout=125", source)

    def test_shared_gemini_http_timeout_and_care_model_fallback(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "main.py").read_text(encoding="utf-8")
        self.assertIn('"timeout": 120000', source)
        self.assertIn('os.getenv("CARE_GEMINI_MODEL", GEMINI_MODEL)', source)
