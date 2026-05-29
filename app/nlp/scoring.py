from __future__ import annotations

from app.nlp.keywords import keyword_score


def score_message_relevance(text: str, has_place: bool, has_time: bool, has_media: bool) -> float:
    return keyword_score(text, has_place=has_place, has_time=has_time, has_media=has_media)

