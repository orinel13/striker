from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta


DATE_PATTERNS = [
    re.compile(r"\b(?P<d>\d{1,2})\.(?P<m>\d{1,2})\.(?P<y>\d{4})\b"),
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b"),
]
TIME_RE = re.compile(r"\b(?P<h>[01]?\d|2[0-3]):(?P<m>[0-5]\d)\b")
DECIMAL_COORD_RE = re.compile(r"(?P<lat>[-+]?\d{1,2}\.\d+)[,\s]+(?P<lon>[-+]?\d{1,3}\.\d+)")
DMS_RE = re.compile(
    r"(?P<lat_d>\d{1,2})°(?P<lat_m>\d{1,2})'(?P<lat_s>\d{1,2})\"?(?P<lat_h>[NS])\s+"
    r"(?P<lon_d>\d{1,3})°(?P<lon_m>\d{1,2})'(?P<lon_s>\d{1,2})\"?(?P<lon_h>[EW])",
    re.IGNORECASE,
)


def extract_date(text: str) -> date | None:
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            return date(int(match["y"]), int(match["m"]), int(match["d"]))
    return None


def extract_time(text: str) -> str | None:
    match = TIME_RE.search(text)
    if not match:
        return None
    return f"{int(match['h']):02d}:{int(match['m']):02d}"


def _dms_to_decimal(deg: str, minute: str, second: str, hemi: str) -> float:
    value = int(deg) + int(minute) / 60 + int(second) / 3600
    if hemi.upper() in {"S", "W"}:
        value *= -1
    return value


def extract_coordinates(text: str) -> tuple[float, float] | None:
    match = DECIMAL_COORD_RE.search(text)
    if match:
        lat = float(match["lat"])
        lon = float(match["lon"])
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    match = DMS_RE.search(text)
    if match:
        return (
            _dms_to_decimal(match["lat_d"], match["lat_m"], match["lat_s"], match["lat_h"]),
            _dms_to_decimal(match["lon_d"], match["lon_m"], match["lon_s"], match["lon_h"]),
        )
    return None


def build_time_window(event_date: date | None, hhmm: str | None) -> tuple[datetime | None, datetime | None]:
    if not event_date:
        return None, None
    if hhmm:
        hour, minute = [int(p) for p in hhmm.split(":", 1)]
        center = datetime.combine(event_date, time(hour, minute))
        return center - timedelta(hours=1), center + timedelta(hours=1)
    return datetime.combine(event_date, time.min), datetime.combine(event_date, time.max)

