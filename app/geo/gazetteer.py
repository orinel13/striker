from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, process
from sqlalchemy.orm import Session

from app.models import Place
from app.telegram.normalizer import normalize_text


@dataclass
class PlaceMatch:
    place: Place
    raw_mention: str
    confidence: float


def _names(place: Place) -> list[str]:
    values = [place.name, place.name_uk, place.name_ru]
    if place.alt_names:
        values.extend(part.strip() for part in place.alt_names.split(";"))
    return [v for v in values if v]


class Gazetteer:
    def __init__(self, session: Session):
        self.session = session
        self.places = list(session.query(Place).all())
        self.index: dict[str, Place] = {}
        for place in self.places:
            for name in _names(place):
                self.index[normalize_text(name)] = place

    def find(self, text: str, fuzzy: bool = True) -> PlaceMatch | None:
        normalized = normalize_text(text)
        for name, place in self.index.items():
            if name and name in normalized:
                return PlaceMatch(place=place, raw_mention=name, confidence=1.0)
        if not fuzzy or not self.index:
            return None
        match = process.extractOne(normalized, self.index.keys(), scorer=fuzz.partial_ratio)
        if match and match[1] >= 88:
            return PlaceMatch(place=self.index[match[0]], raw_mention=match[0], confidence=match[1] / 100)
        return None

