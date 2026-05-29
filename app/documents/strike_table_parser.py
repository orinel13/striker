from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

from docx import Document


@dataclass
class ParsedStrikeRow:
    raw_text: str
    row_index: int
    date_raw: str | None = None
    event_date: date | None = None
    time_raw: str | None = None
    event_time_local: str | None = None
    time_range_start: str | None = None
    time_range_end: str | None = None
    time_window_start: datetime | None = None
    time_window_end: datetime | None = None
    oblast: str | None = None
    place_name_raw: str | None = None
    reference_text: str | None = None
    raw_grid_northing: str | None = None
    raw_grid_easting: str | None = None
    coordinate_source: str | None = None
    lat: float | None = None
    lon: float | None = None
    parser_warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DocumentPeriod:
    start_date: date
    end_date: date | None = None
    night_mode: bool = False
    rollover_hour: int = 12


DASH_RE = re.compile(r"[\u2010-\u2015\u2212]")
SPACE_RE = re.compile(r"\s+")
SHORT_TOKEN_RE = re.compile(r"\b(?P<a>\d{1,2})[.:](?P<b>\d{2})(?:[.,])?\b")
FULL_DMY_RE = re.compile(r"\b(?P<d>\d{1,2})\.(?P<m>\d{1,2})\.(?P<y>\d{4})\b")
FULL_YMD_RE = re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b")
GRID_RE = re.compile(r"\b(?P<northing>\d{7})\s+(?P<easting>[3-8]\d{6})\b")

PLACE_ALIASES = {
    "Днепропетровск": "Днепр",
    "Красноармейск": "Покровск",
    "Елизаветград": "Кропивницкий",
    "Артемовск": "Бахмут",
    "Дзержинск": "Торецк",
    "Орджоникидзе": "Покров",
    "Доброполье": "Добропілля",
    "Славянск": "Слов'янськ",
    "Балаклея": "Балаклія",
    "Изюм": "Ізюм",
    "Чугуев": "Чугуїв",
}

OBLAST_PATTERNS = [
    ("Харьковская обл.", re.compile(r"\bХарьковск(?:ая|ой)\s+обл(?:\.|асть)?", re.IGNORECASE)),
    ("Днепропетровская обл.", re.compile(r"\bДнепропетровск(?:ая|ой)\s+обл(?:\.|асть)?", re.IGNORECASE)),
    ("Одесская обл.", re.compile(r"\bОдесск(?:ая|ой)\s+обл(?:\.|асть)?", re.IGNORECASE)),
    ("Сумская обл.", re.compile(r"\bСумск(?:ая|ой)\s+обл(?:\.|асть)?", re.IGNORECASE)),
    ("ДНР", re.compile(r"\bДНР\b", re.IGNORECASE)),
    ("Николаевская обл.", re.compile(r"\bНиколаевск(?:ая|ой)\s+обл(?:\.|асть)?", re.IGNORECASE)),
    ("Кировоградская обл.", re.compile(r"\bКировоградск(?:ая|ой)\s+обл(?:\.|асть)?", re.IGNORECASE)),
    ("Полтавская обл.", re.compile(r"\bПолтавск(?:ая|ой)\s+обл(?:\.|асть)?", re.IGNORECASE)),
    ("Черниговская обл.", re.compile(r"\bЧерниговск(?:ая|ой)\s+обл(?:\.|асть)?", re.IGNORECASE)),
    ("Киевская обл.", re.compile(r"\bКиевск(?:ая|ой)\s+обл(?:\.|асть)?", re.IGNORECASE)),
]


def normalize_time_text(text: str) -> str:
    text = DASH_RE.sub("-", text or "")
    text = text.replace("\r", " ").replace("\n", " ")
    return SPACE_RE.sub(" ", text).strip()


def _format_hhmm(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _parse_time_token(token: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(?P<h>\d{1,2})[.:](?P<m>\d{2})\s*", token)
    if not match:
        return None
    hour = int(match["h"])
    minute = int(match["m"])
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def choose_event_date_for_time(hour: int, period: DocumentPeriod | None, fallback_date: date | None) -> date | None:
    if period is None:
        return fallback_date
    if not period.night_mode:
        return period.start_date
    if period.end_date is not None and hour < period.rollover_hour:
        return period.end_date
    return period.start_date


def parse_time_or_range(text: str, base_date: date | None, period: DocumentPeriod | None = None) -> dict:
    normalized = normalize_time_text(text)
    warnings: list[str] = []
    result = {
        "time_raw": normalized or None,
        "event_time_local": None,
        "time_range_start": None,
        "time_range_end": None,
        "time_window_start": None,
        "time_window_end": None,
        "parser_warnings": warnings,
    }
    matches = list(SHORT_TOKEN_RE.finditer(normalized))
    time_tokens = [m.group(0).rstrip(".,") for m in matches if _parse_time_token(m.group(0).rstrip(".,"))]
    if not time_tokens:
        return result
    if len(time_tokens) >= 2 and re.search(r"\d{1,2}[.:]\d{2}\s*-\s*\d{1,2}[.:]\d{2}", normalized):
        start_h, start_m = _parse_time_token(time_tokens[0]) or (0, 0)
        end_h, end_m = _parse_time_token(time_tokens[1]) or (0, 0)
        start_text = _format_hhmm(start_h, start_m)
        end_text = _format_hhmm(end_h, end_m)
        result["time_range_start"] = start_text
        result["time_range_end"] = end_text
        start_date = choose_event_date_for_time(start_h, period, base_date)
        end_date = choose_event_date_for_time(end_h, period, base_date)
        if start_date and end_date:
            if period is None and base_date and (end_h, end_m) < (start_h, start_m):
                end_date = base_date + timedelta(days=1)
            start_dt = datetime.combine(start_date, time(start_h, start_m))
            end_dt = datetime.combine(end_date, time(end_h, end_m))
            result["time_window_start"] = start_dt - timedelta(hours=1)
            result["time_window_end"] = end_dt + timedelta(hours=1)
        else:
            warnings.append("missing document date")
        return result
    hour, minute = _parse_time_token(time_tokens[-1]) or (0, 0)
    event_time = _format_hhmm(hour, minute)
    result["event_time_local"] = event_time
    event_date = choose_event_date_for_time(hour, period, base_date)
    if event_date:
        center = datetime.combine(event_date, time(hour, minute))
        result["time_window_start"] = center - timedelta(hours=1)
        result["time_window_end"] = center + timedelta(hours=1)
    else:
        warnings.append("missing document date")
    return result


def parse_short_date_token(text: str, default_year: int | None) -> date | None:
    for pattern in (FULL_DMY_RE, FULL_YMD_RE):
        match = pattern.search(text or "")
        if match:
            return date(int(match["y"]), int(match["m"]), int(match["d"]))
    if default_year is None:
        return None
    tokens = list(SHORT_TOKEN_RE.finditer(text or ""))
    if not tokens:
        return None
    first = tokens[0]
    day = int(first["a"])
    month = int(first["b"])
    if 1 <= day <= 31 and 1 <= month <= 12:
        return date(default_year, month, day)
    return None


def parse_oblast(text: str) -> str | None:
    for value, pattern in OBLAST_PATTERNS:
        if pattern.search(text or ""):
            return value
    return None


def _normalize_place_name(name: str) -> str:
    name = SPACE_RE.sub(" ", name.strip(" .;,:()"))
    return PLACE_ALIASES.get(name, name)


def parse_place_or_reference(text: str) -> tuple[str | None, str | None]:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    place_name: str | None = None
    references: list[str] = []
    np_re = re.compile(r"\bн\.?\s*п\.?\s+(?P<name>[^()\n\r]+)", re.IGNORECASE)
    distance_re = re.compile(
        r"(?P<ref>\d+(?:,\d+)?\s*км\s+[а-яё-]+\.\s+(?P<place>[А-Яа-яЁёІіЇїЄєҐґ'’\-\s]+))",
        re.IGNORECASE,
    )
    parenthetical_ref_re = re.compile(r"\((?P<ref>\d+(?:,\d+)?\s*км\s+[^)]+)\)", re.IGNORECASE)
    match = np_re.search(text or "")
    if match:
        place_name = _normalize_place_name(match["name"])
    for line in lines:
        distance_match = distance_re.search(line)
        if distance_match:
            references.append(distance_match["ref"].strip())
            if not place_name:
                place_name = _normalize_place_name(distance_match["place"])
    for match in parenthetical_ref_re.finditer(text or ""):
        references.append(match["ref"].strip())
        if not place_name:
            tail = match["ref"].split()[-1]
            place_name = _normalize_place_name(tail)
    return place_name, "; ".join(dict.fromkeys(references)) or None


def parse_sk42_gauss_kruger(text: str) -> tuple[float, float, str, str, str] | None:
    match = GRID_RE.search(text or "")
    if not match:
        return None
    northing = match["northing"]
    easting = match["easting"]
    zone = int(easting[0])
    epsg = 28400 + zone
    from pyproj import Transformer

    transformer = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(float(easting), float(northing))
    if 44 <= lat <= 53 and 22 <= lon <= 41:
        return lat, lon, f"sk42_gauss_kruger_zone_{zone}", northing, easting
    return None


def _split_cells(row) -> tuple[str, str] | None:
    cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
    if not cells:
        return None
    return cells[0], "\n".join(cells[1:])


def _time_text_without_date(time_cell: str, event_date: date | None) -> str:
    text = normalize_time_text(time_cell)
    tokens = list(SHORT_TOKEN_RE.finditer(text))
    if event_date and tokens:
        first = tokens[0]
        token_date = f"{int(first['a']):02d}.{int(first['b']):02d}"
        if event_date.strftime("%d.%m") == token_date:
            return text[first.end() :].lstrip(" ,;")
    return text


def parse_docx_strike_rows(
    path: Path | str,
    document_date: date | None = None,
    default_year: int | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    night_mode: bool = False,
    rollover_hour: int = 12,
) -> list[ParsedStrikeRow]:
    doc = Document(str(path))
    rows: list[ParsedStrikeRow] = []
    period = DocumentPeriod(period_start, period_end, night_mode, rollover_hour) if period_start else None
    current_date = period_start or document_date
    row_index = 0
    for table in doc.tables:
        for docx_row in table.rows:
            split = _split_cells(docx_row)
            if not split:
                continue
            row_index += 1
            time_cell, detail_cell = split
            raw_text = "\n".join(part for part in [time_cell, detail_cell] if part)
            warnings: list[str] = []
            row_date = parse_short_date_token(time_cell, default_year)
            if row_date:
                current_date = row_date
            elif period:
                row_date = period.start_date
            elif document_date:
                row_date = document_date
            elif current_date:
                row_date = current_date
            elif SHORT_TOKEN_RE.search(time_cell) and default_year is None:
                warnings.append("missing document date")
            time_text = _time_text_without_date(time_cell, row_date)
            time_info = parse_time_or_range(time_text, row_date, period=period)
            if period and time_info["time_window_start"]:
                row_date = time_info["time_window_start"].date()
                if time_info["event_time_local"]:
                    token = time_info["event_time_local"]
                    hour = int(token.split(":", 1)[0])
                    row_date = choose_event_date_for_time(hour, period, row_date)
            warnings.extend(time_info["parser_warnings"])
            oblast = parse_oblast(detail_cell)
            place, reference = parse_place_or_reference(detail_cell)
            parsed = ParsedStrikeRow(
                raw_text=raw_text,
                row_index=row_index,
                date_raw=time_cell if row_date else None,
                event_date=row_date,
                time_raw=time_info["time_raw"],
                event_time_local=time_info["event_time_local"],
                time_range_start=time_info["time_range_start"],
                time_range_end=time_info["time_range_end"],
                time_window_start=time_info["time_window_start"],
                time_window_end=time_info["time_window_end"],
                oblast=oblast,
                place_name_raw=place,
                reference_text=reference,
                parser_warnings=list(dict.fromkeys(warnings)),
            )
            grid_match = GRID_RE.search(detail_cell)
            grid = parse_sk42_gauss_kruger(detail_cell)
            if grid:
                parsed.lat, parsed.lon, parsed.coordinate_source, parsed.raw_grid_northing, parsed.raw_grid_easting = grid
            elif grid_match:
                parsed.raw_grid_northing = grid_match["northing"]
                parsed.raw_grid_easting = grid_match["easting"]
                parsed.parser_warnings.append("sk42 coordinate outside Ukraine or invalid")
            rows.append(parsed)
    return rows
