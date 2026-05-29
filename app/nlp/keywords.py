from __future__ import annotations

from pathlib import Path

import yaml

from app.telegram.normalizer import normalize_text


DEFAULT_KEYWORDS_PATH = Path("data/keywords.yml")


def load_keywords(path: Path | str = DEFAULT_KEYWORDS_PATH) -> dict[str, dict[str, list[str]]]:
    with Path(path).open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def flatten_keywords(keywords: dict[str, dict[str, list[str]]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for category, languages in keywords.items():
        items: list[str] = []
        for values in languages.values():
            items.extend(normalize_text(v) for v in values)
        result[category] = sorted(set(items), key=len, reverse=True)
    return result


def find_keywords(text: str, keywords: dict[str, dict[str, list[str]]] | None = None) -> list[tuple[str, str]]:
    keywords = keywords or load_keywords()
    normalized = normalize_text(text)
    matches: list[tuple[str, str]] = []
    for category, words in flatten_keywords(keywords).items():
        for word in words:
            if word and word in normalized:
                matches.append((category, word))
    return matches


def keyword_score(text: str, has_place: bool = False, has_time: bool = False, has_media: bool = False) -> float:
    categories = {category for category, _ in find_keywords(text)}
    score = 0.0
    if {"uav", "missile"} & categories:
        score += 0.3
    if {"impact", "fire"} & categories:
        score += 0.3
    if "air_defense" in categories:
        score += 0.12
    if has_place:
        score += 0.15
    if has_time:
        score += 0.08
    if has_media:
        score += 0.08
    if categories == {"air_defense"}:
        score *= 0.65
    if ("сводка" in text.lower() or "зведення" in text.lower()) and not has_place:
        score -= 0.15
    return max(0.0, min(1.0, score))

