from __future__ import annotations

from pathlib import Path

from docx import Document
from sqlalchemy.orm import Session

from app.config import get_settings
from app.geo.gazetteer import Gazetteer
from app.models import Case
from app.nlp.extractors import build_time_window, extract_coordinates, extract_date, extract_time


def iter_docx_blocks(path: Path | str) -> list[str]:
    doc = Document(str(path))
    blocks: list[str] = []
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if text:
            blocks.append(text)
    for table in doc.tables:
        for row in table.rows:
            values = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if values:
                blocks.append(" | ".join(values))
    return blocks


def import_docx(session: Session, path: Path | str) -> list[Case]:
    settings = get_settings()
    source = str(path)
    gazetteer = Gazetteer(session)
    cases: list[Case] = []
    for block in iter_docx_blocks(path):
        event_date = extract_date(block)
        event_time = extract_time(block)
        coords = extract_coordinates(block)
        place_match = gazetteer.find(block)
        lat = coords[0] if coords else (place_match.place.lat if place_match else None)
        lon = coords[1] if coords else (place_match.place.lon if place_match else None)
        place_name = place_match.place.name if place_match else None
        window_start, window_end = build_time_window(event_date, event_time)
        if not any([event_date, coords, place_match]):
            continue
        case = Case(
            source_docx=source,
            raw_text=block,
            event_date=event_date,
            event_time_local=event_time,
            time_window_start=window_start,
            time_window_end=window_end,
            place_name=place_name,
            lat=lat,
            lon=lon,
            radius_km=settings.firms_default_radius_km,
        )
        session.add(case)
        cases.append(case)
    session.flush()
    return cases

