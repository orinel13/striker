from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.geo.distance import haversine_km
from app.models import Case, FirmsPoint


FIRMS_CAVEAT = (
    "FIRMS показывает thermal anomaly / active fire detection. "
    "Это не самостоятельное доказательство причины пожара и требует контекстной проверки."
)


def nearby_firms_points(session: Session, case: Case) -> list[FirmsPoint]:
    if case.lat is None or case.lon is None or not case.event_date:
        return []
    start = case.event_date - timedelta(days=1)
    end = case.event_date + timedelta(days=1)
    points = session.query(FirmsPoint).filter(FirmsPoint.acq_date >= start, FirmsPoint.acq_date <= end).all()
    return [p for p in points if haversine_km(case.lat, case.lon, p.lat, p.lon) <= case.radius_km]

