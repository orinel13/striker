from __future__ import annotations


UK_MARKERS = set("іїєґ")
RU_MARKERS = {"ы", "э", "ъ"}


def detect_language(text: str) -> str | None:
    lowered = text.lower()
    if any(ch in lowered for ch in UK_MARKERS):
        return "uk"
    if any(ch in lowered for ch in RU_MARKERS):
        return "ru"
    return None

