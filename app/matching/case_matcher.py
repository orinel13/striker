from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.firms.matcher import FIRMS_CAVEAT, nearby_firms_points
from app.geo.distance import haversine_km
from app.models import Case, CaseMatch, Message, MessagePlace
from app.nlp.keywords import find_keywords


def time_score(case: Case, posted_at: datetime) -> float:
    if case.time_window_start and case.time_window_end and case.time_window_start <= posted_at <= case.time_window_end:
        return 1.0
    if case.time_window_start and abs(posted_at - case.time_window_start) <= timedelta(hours=6):
        return 0.75
    if case.event_date and posted_at.date() == case.event_date:
        return 0.45
    if case.event_date and posted_at.date() == case.event_date + timedelta(days=1):
        return 0.25
    return 0.0


def geo_score(session: Session, case: Case, message: Message) -> float:
    if case.lat is None or case.lon is None:
        return 0.0
    places = session.query(MessagePlace).filter(MessagePlace.message_id == message.id).all()
    for place in places:
        if place.lat is not None and place.lon is not None and haversine_km(case.lat, case.lon, place.lat, place.lon) <= case.radius_km:
            return 1.0
    if case.place_name and case.place_name.lower() in message.normalized_text:
        return 0.7
    return 0.0


def keyword_match_score(message: Message) -> float:
    categories = {category for category, _ in find_keywords(message.text)}
    if ({"uav", "missile"} & categories) and ({"impact", "fire"} & categories):
        return 1.0
    if "air_defense" in categories and len(categories) == 1:
        return 0.35
    if categories:
        return 0.55
    return 0.0


def priority_for(total: float, t_score: float) -> str:
    if total >= 0.82 and t_score >= 1.0:
        return "A"
    if total >= 0.68:
        return "B"
    if t_score in {0.45, 0.25}:
        return "C"
    return "NO DATA"


def explanation(priority: str, message: Message | None = None) -> str:
    if message:
        return (
            f"Приоритет {priority}: сообщение совпадает с кейсом по времени, месту и тематическим признакам. "
            "Это ретроспективное сопоставление архивных данных, не live tracking."
        )
    return "NO DATA: в архиве Telegram и FIRMS не найдено достаточно данных для уверенного сопоставления."


def match_cases(session: Session) -> int:
    settings = get_settings()
    cutoff = datetime.utcnow() - timedelta(minutes=settings.min_archive_delay_minutes)
    session.query(CaseMatch).delete()
    count = 0
    messages = session.query(Message).filter(Message.posted_at <= cutoff).all()
    for case in session.query(Case).all():
        added = False
        for message in messages:
            t_score = time_score(case, message.posted_at)
            if t_score <= 0:
                continue
            g_score = geo_score(session, case, message)
            k_score = keyword_match_score(message)
            source_score = 0.1 if message.url else 0.0
            total = round(t_score * 0.35 + g_score * 0.3 + k_score * 0.25 + source_score, 3)
            priority = priority_for(total, t_score)
            if priority == "NO DATA":
                continue
            session.add(
                CaseMatch(
                    case_id=case.id,
                    message_id=message.id,
                    match_type="telegram",
                    time_score=t_score,
                    geo_score=g_score,
                    keyword_score=k_score,
                    source_score=source_score,
                    total_score=total,
                    priority=priority,
                    explanation=explanation(priority, message),
                )
            )
            count += 1
            added = True
        for point in nearby_firms_points(session, case):
            session.add(
                CaseMatch(
                    case_id=case.id,
                    firms_point_id=point.id,
                    match_type="firms",
                    time_score=0.45,
                    geo_score=1.0,
                    keyword_score=0.0,
                    source_score=0.2,
                    total_score=0.65,
                    priority="FIRMS+" if point.acq_date == case.event_date else "FIRMS?",
                    explanation=FIRMS_CAVEAT,
                )
            )
            count += 1
            added = True
        if not added:
            session.add(
                CaseMatch(
                    case_id=case.id,
                    match_type="none",
                    priority="NO DATA",
                    explanation=explanation("NO DATA"),
                )
            )
            count += 1
    return count

