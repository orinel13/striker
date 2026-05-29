from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import get_settings
from app.firms.matcher import FIRMS_CAVEAT, nearby_firms_points
from app.geo.distance import haversine_km
from app.models import Case, CaseMatch, Channel, Message, MessagePlace
from app.nlp.keywords import find_keywords
from app.telegram.normalizer import normalize_text


PLACE_ALIASES = {
    "краматорск": ["краматорск", "краматорськ", "kramatorsk"],
    "краматорськ": ["краматорск", "краматорськ", "kramatorsk"],
    "славянск": ["славянск", "слов'янськ", "словянськ", "slavyansk", "sloviansk", "slovyansk"],
    "слов'янськ": ["славянск", "слов'янськ", "словянськ", "slavyansk", "sloviansk", "slovyansk"],
    "дружковка": ["дружковка", "дружківка", "druzhkovka"],
    "дружківка": ["дружковка", "дружківка", "druzhkovka"],
    "константиновка": ["константиновка", "костянтинівка", "konstantinovka"],
    "костянтинівка": ["константиновка", "костянтинівка", "konstantinovka"],
    "доброполье": ["доброполье", "добропілля", "dobropillya", "dobropilia"],
    "добропілля": ["доброполье", "добропілля", "dobropillya", "dobropilia"],
    "прилуки": ["прилуки", "pryluky"],
    "чернигов": ["чернигов", "чернігів", "chernihiv"],
    "чернігів": ["чернигов", "чернігів", "chernihiv"],
    "харьков": ["харьков", "харків", "kharkiv"],
    "харків": ["харьков", "харків", "kharkiv"],
    "чугуев": ["чугуев", "чугуїв", "chuguev", "chuhuiv"],
    "чугуїв": ["чугуев", "чугуїв", "chuguev", "chuhuiv"],
    "балаклея": ["балаклея", "балаклія", "balakliya"],
    "балаклія": ["балаклея", "балаклія", "balakliya"],
    "изюм": ["изюм", "ізюм", "izyum", "izium"],
    "ізюм": ["изюм", "ізюм", "izyum", "izium"],
    "днепр": ["днепр", "дніпро", "днепропетровск", "dnipro"],
    "дніпро": ["днепр", "дніпро", "днепропетровск", "dnipro"],
    "днепропетровск": ["днепр", "дніпро", "днепропетровск", "dnipro"],
    "павлоград": ["павлоград", "pavlograd"],
    "одесса": ["одесса", "одеса", "odesa", "odessa"],
    "одеса": ["одесса", "одеса", "odesa", "odessa"],
    "конотоп": ["конотоп", "konotop"],
    "кропивницкий": ["кировоград", "кропивницкий", "кропивницький", "kropyvnytskyi"],
    "кропивницький": ["кировоград", "кропивницкий", "кропивницький", "kropyvnytskyi"],
    "кировоград": ["кировоград", "кропивницкий", "кропивницький", "kropyvnytskyi"],
    "красноармейск": ["покровск", "покровськ"],
}


def localize_message_time(posted_at: datetime, timezone_name: str | None = None) -> datetime:
    timezone = ZoneInfo(timezone_name or get_settings().local_timezone)
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=UTC)
    return posted_at.astimezone(timezone).replace(tzinfo=None)


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
    place_aliases = _place_aliases(case.place_name)
    if place_aliases and any(alias in message.normalized_text for alias in place_aliases):
        return 0.7
    if case.lat is not None and case.lon is not None:
        places = session.query(MessagePlace).filter(MessagePlace.message_id == message.id).all()
        for place in places:
            if place.lat is not None and place.lon is not None and haversine_km(case.lat, case.lon, place.lat, place.lon) <= case.radius_km:
                return 1.0
    channel = session.get(Channel, message.channel_id)
    channel_text = normalize_text(" ".join([channel.username or "", channel.title or ""])) if channel else ""
    categories = {category for category, _ in find_keywords(message.text)}
    if place_aliases and any(alias in channel_text for alias in place_aliases) and (categories & {"impact", "fire", "uav", "missile"}):
        return 0.45
    return 0.0


def _place_aliases(place_name: str | None) -> list[str]:
    if not place_name:
        return []
    base = normalize_text(place_name)
    aliases = {base}
    aliases.update(PLACE_ALIASES.get(base, []))
    for old, values in PLACE_ALIASES.items():
        if base in values:
            aliases.add(old)
            aliases.update(values)
    return [normalize_text(alias) for alias in aliases if alias]


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


def _cap_priority_for_indirect_geo(priority: str, g_score: float) -> str:
    if g_score < 0.7 and priority == "A":
        return "B"
    return priority


def score_message_for_case(session: Session, case: Case, message: Message) -> dict:
    settings = get_settings()
    posted_at_local = localize_message_time(message.posted_at, settings.local_timezone)
    t_score = time_score(case, posted_at_local)
    g_score = geo_score(session, case, message)
    k_score = keyword_match_score(message)
    source_score = 0.1 if message.url else 0.0
    total = round(t_score * 0.35 + g_score * 0.3 + k_score * 0.25 + source_score, 3)
    priority = _cap_priority_for_indirect_geo(priority_for(total, t_score), g_score)
    reasons = []
    if t_score <= 0:
        reasons.append("rejected_time")
    if g_score <= 0:
        reasons.append("rejected_geo")
    if k_score <= 0:
        reasons.append("rejected_keyword")
    if priority == "NO DATA":
        reasons.append("rejected_total")
    return {
        "posted_at_local": posted_at_local,
        "time_score": t_score,
        "geo_score": g_score,
        "keyword_score": k_score,
        "source_score": source_score,
        "total": total,
        "priority": priority,
        "reasons": reasons,
    }


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
            scored = score_message_for_case(session, case, message)
            t_score = scored["time_score"]
            if t_score <= 0:
                continue
            g_score = scored["geo_score"]
            k_score = scored["keyword_score"]
            source_score = scored["source_score"]
            total = scored["total"]
            priority = scored["priority"]
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
