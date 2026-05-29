from __future__ import annotations

import csv
import io
import json
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Case, FirmsPoint


FIRMS_SOURCES = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT"]


def bbox_for_radius(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    delta_lat = radius_km / 111.0
    delta_lon = radius_km / max(1.0, 111.0)
    return lon - delta_lon, lat - delta_lat, lon + delta_lon, lat + delta_lat


def _parse_datetime_utc(acq_date: str | None, acq_time: str | None) -> datetime | None:
    if not acq_date or not acq_time:
        return None
    padded = acq_time.zfill(4)
    try:
        return datetime.strptime(f"{acq_date} {padded}", "%Y-%m-%d %H%M")
    except ValueError:
        return None


def normalize_row(row: dict[str, str], source: str, case_id: int | None) -> FirmsPoint:
    lat = float(row.get("latitude") or row.get("lat") or 0)
    lon = float(row.get("longitude") or row.get("lon") or 0)
    acq_date_raw = row.get("acq_date")
    acq_date = datetime.strptime(acq_date_raw, "%Y-%m-%d").date() if acq_date_raw else None
    return FirmsPoint(
        case_id=case_id,
        source=source,
        satellite=row.get("satellite"),
        instrument=row.get("instrument"),
        lat=lat,
        lon=lon,
        acq_date=acq_date,
        acq_time=row.get("acq_time"),
        acq_datetime_utc=_parse_datetime_utc(acq_date_raw, row.get("acq_time")),
        confidence=row.get("confidence"),
        frp=float(row["frp"]) if row.get("frp") not in (None, "") else None,
        brightness=float(row.get("bright_ti4") or row.get("brightness") or 0) or None,
        daynight=row.get("daynight"),
        raw_json=json.dumps(row, ensure_ascii=False),
    )


def fetch_firms_for_case(session: Session, case: Case) -> int:
    settings = get_settings()
    if not settings.firms_map_key or case.lat is None or case.lon is None or not case.event_date:
        return 0
    west, south, east, north = bbox_for_radius(case.lat, case.lon, case.radius_km)
    area = f"{west},{south},{east},{north}"
    day = case.event_date.isoformat()
    count = 0
    with httpx.Client(timeout=60) as client:
        for source in FIRMS_SOURCES:
            url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{settings.firms_map_key}/{source}/{area}/1/{day}"
            response = client.get(url)
            response.raise_for_status()
            reader = csv.DictReader(io.StringIO(response.text))
            for row in reader:
                session.add(normalize_row(row, source=source, case_id=case.id))
                count += 1
    return count


def fetch_firms_for_all_cases(session: Session) -> int:
    total = 0
    for case in session.query(Case).all():
        total += fetch_firms_for_case(session, case)
    return total

