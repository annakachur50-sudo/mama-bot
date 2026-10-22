import os
import re

# The workflow supplies a real GOOGLE_API_KEY. A dummy Telegram token only lets
# main.py initialize its Bot object; this script never contacts Telegram.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")

import main


SAMPLES = (
    ("3 года", {"child_number": 1, "age_value": 3, "age_unit": "years"}),
    ("7 лет", {"child_number": 1, "age_value": 7, "age_unit": "years"}),
    ("11 лет", {"child_number": 1, "age_value": 11, "age_unit": "years"}),
    ("14 лет", {"child_number": 1, "age_value": 14, "age_unit": "years"}),
)


def main_test():
    outputs = {}
    for label, age in SAMPLES:
        result = main.generate_kids_activity_sync([age])
        if not result.strip():
            raise AssertionError(f"Gemini returned an empty activity for {label}")
        outputs[label] = result.strip()
        print(f"\n===== REAL GEMINI OUTPUT: {label} =====\n{outputs[label]}\n")

    teen_text = outputs["14 лет"].casefold()
    prohibited_patterns = (
        r"давай.{0,30}прятки",
        r"сыграем.{0,30}прятки",
        r"изобрази.{0,30}персонаж",
        r"покажи.{0,30}животн.{0,30}без слов",
        r"пантомим",
    )
    for pattern in prohibited_patterns:
        if re.search(pattern, teen_text):
            raise AssertionError(f"Teen output may be too childish (matched {pattern!r})")

    if len({text.casefold() for text in outputs.values()}) < 4:
        raise AssertionError("Age samples did not produce four distinct activities")
    print("\nAll four real Gemini samples returned distinct, non-empty activities; teen restrictions passed.")


if __name__ == "__main__":
    main_test()
