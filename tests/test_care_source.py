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


if __name__ == "__main__":
    unittest.main()
