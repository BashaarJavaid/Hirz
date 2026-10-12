"""Shared strict phone normalization; no inferred international country codes."""

import re


def phone(text: str) -> str:
    if not re.fullmatch(r"\+?[0-9 ().-]+", text):
        raise ValueError("Provide a phone number without extensions or letters.")
    digits = re.sub(r"[ ().-]", "", text)
    if digits.startswith("+"):
        if not 8 <= len(digits) - 1 <= 15:
            raise ValueError("International numbers need eight through fifteen digits.")
        return digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    raise ValueError("International numbers require an explicit plus country code.")
