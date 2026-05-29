from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.firms.matcher import FIRMS_CAVEAT, nearby_firms_points
from app.geo.distance import haversine_km
from app.models import Case, CaseMatch, Channel, Message, MessageKeyword, MessagePlace
from app.telegram.normalizer import normalize_text


STRONG_IMPACT = [
    "прилет",
    "приліт",
    "прилетело",
    "прилетіло",
    "влучання",
    "попадание",
    "удар",
    "обстрел",
    "обстріл",
    "атаковали",
    "атака",
    "вибух",
    "взрыв",
    "пожар",
    "пожежа",
    "горит",
    "горить",
    "дым",
    "дим",
    "пошкоджено",
    "повреждено",
    "зруйновано",
    "разрушено",
    "ранен",
    "поранен",
    "наслідки",
    "последствия",
]
THREAT_ONLY = ["каб", "бпла", "шахед", "дрон", "ракета", "ракети", "курсом", "загроза", "укрытие"]
AIR_ALERT = ["тревога", "тривога", "повітряна", "воздушная"]
NOISE = [
    "перевозки",
    "грузоперевозки",
    "стрижки",
    "маникюр",
    "манікюр",
    "педикюр",
    "вакансии",
    "вакансії",
    "дюсш",
    "чемпионат",
    "чемпіонат",
    "купить",
    "продажа",
    "продаж",
    "доставка",
    "маршрут",
    "пассажирские перевозки",
    "пассажирские",
    "работа",
    "робота",
    "спорт",
    "ліцей",
    "лицей",
    "навчальний простір",
    "суд",
    "сизо",
    "сізо",
    "мер",
    "блогер",
    "блогерка",
    "косметолог",
    "силікон",
    "силикон",
    "школа",
]
GENERIC_THREAT = ["масований ракетний удар", "массовый ракетный удар", "ймовірність комбінованої атаки", "комбінованої атаки", "зліт міг-31к", "миг-31к"]
GENERIC_MONITOR_CHANNELS = ["war_monitor", "eradarrua", "radar_plus_bpla", "povitryanatrivogaaa", "monitor"]

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


@dataclass
class PreparedMessage:
    message: Message
    channel: Channel | None
    places: list[MessagePlace]
    keyword_categories: set[str]
    posted_at_local: datetime


@dataclass
class ScoreResult:
    time_score: float
    geo_score: float
    keyword_score: float
    source_score: float
    total: float
    priority: str
    reasons: list[str]
    geo_direct: bool
    strong_impact: bool
    threat_only: bool
    generic_channel: bool


def localize_message_time(posted_at: datetime, timezone_name: str | None = None) -> datetime:
    timezone = ZoneInfo(timezone_name or get_settings().local_timezone)
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=UTC)
    return posted_at.astimezone(timezone).replace(tzinfo=None)


def _local_to_utc_naive(dt: datetime, timezone_name: str) -> datetime:
    return dt.replace(tzinfo=ZoneInfo(timezone_name)).astimezone(UTC).replace(tzinfo=None)


def _case_aliases(case: Case) -> list[str]:
    base_values = [case.place_name, case.reference_text]
    aliases: set[str] = set()
    for value in base_values:
        if not value:
            continue
        base = normalize_text(value)
        aliases.add(base)
        aliases.update(PLACE_ALIASES.get(base, []))
        for key, values in PLACE_ALIASES.items():
            norm_values = {normalize_text(v) for v in values}
            if base == key or base in norm_values:
                aliases.add(key)
                aliases.update(norm_values)
    return sorted({normalize_text(alias) for alias in aliases if alias}, key=len, reverse=True)


def _contains_any(text: str, words: list[str]) -> bool:
    return any(word in text for word in words)


def _contains_alias_token(text: str, aliases: list[str]) -> bool:
    for alias in aliases:
        if not alias:
            continue
        if re.search(rf"(?<![0-9a-zа-яіїєґ]){re.escape(alias)}(?![0-9a-zа-яіїєґ])", text, re.IGNORECASE):
            return True
    return False


def _keyword_score(text: str) -> tuple[float, bool, bool, list[str]]:
    strong = _contains_any(text, STRONG_IMPACT)
    threat = _contains_any(text, THREAT_ONLY)
    alert = _contains_any(text, AIR_ALERT)
    noise = _contains_any(text, NOISE)
    reasons: list[str] = []
    if noise and not strong:
        return 0.0, False, False, ["rejected_noise"]
    if strong:
        return 1.0, True, False, reasons
    if threat:
        return 0.75, False, True, reasons
    if alert:
        return 0.2, False, False, reasons
    return 0.0, False, False, ["rejected_keyword"]


def evidence_window(case: Case, timezone_name: str | None = None) -> tuple[datetime, datetime]:
    timezone_name = timezone_name or get_settings().local_timezone
    if case.time_window_start and case.time_window_end:
        start_local = case.time_window_start - timedelta(hours=3)
        end_local = case.time_window_end + timedelta(hours=18)
    elif case.event_date:
        start_local = datetime.combine(case.event_date, time.min)
        end_local = datetime.combine(case.event_date + timedelta(days=1), time.max)
    else:
        end_local = datetime.utcnow()
        start_local = end_local - timedelta(days=3)
    return _local_to_utc_naive(start_local, timezone_name), _local_to_utc_naive(end_local, timezone_name)


def time_score(case: Case, posted_at_local: datetime) -> float:
    if case.time_window_start and case.time_window_end:
        if case.time_window_start <= posted_at_local <= case.time_window_end:
            return 1.0
        if case.time_window_end < posted_at_local <= case.time_window_end + timedelta(hours=6):
            return 0.75
        if case.time_window_end < posted_at_local <= case.time_window_end + timedelta(hours=18):
            return 0.55
        if case.event_date and posted_at_local.date() in {case.event_date, case.event_date + timedelta(days=1)}:
            return 0.35
        return 0.0
    if case.event_date and posted_at_local.date() in {case.event_date, case.event_date + timedelta(days=1)}:
        return 0.35
    return 0.0


def _channel_text(channel: Channel | None) -> str:
    return normalize_text(" ".join([channel.username or "", channel.title or ""])) if channel else ""


def _is_generic_monitor(channel: Channel | None) -> bool:
    text = _channel_text(channel)
    return any(marker in text for marker in GENERIC_MONITOR_CHANNELS)


def geo_score_preloaded(case: Case, prepared: PreparedMessage, aliases: list[str]) -> tuple[float, bool, bool]:
    text = prepared.message.normalized_text
    if aliases and _contains_alias_token(text, aliases):
        return 0.85, True, False
    if case.lat is not None and case.lon is not None:
        for place in prepared.places:
            if place.lat is not None and place.lon is not None and haversine_km(case.lat, case.lon, place.lat, place.lon) <= case.radius_km:
                return 1.0, True, False
    if aliases and _contains_any(_channel_text(prepared.channel), aliases):
        return 0.65, False, True
    return 0.0, False, False


def geo_score(session: Session, case: Case, message: Message) -> float:
    channel = session.get(Channel, message.channel_id)
    places = session.query(MessagePlace).filter(MessagePlace.message_id == message.id).all()
    prepared = PreparedMessage(message, channel, places, set(), localize_message_time(message.posted_at))
    return geo_score_preloaded(case, prepared, _case_aliases(case))[0]


def _priority(total: float, time_value: float, geo_direct: bool, strong: bool, threat_only: bool, geo_channel_only: bool) -> str:
    if total >= 0.82 and geo_direct and strong and time_value >= 0.75:
        return "A"
    if total >= 0.65:
        return "C" if threat_only and not geo_direct else "B"
    if total >= 0.50:
        return "C"
    return "NO DATA"


def score_prepared_message(case: Case, prepared: PreparedMessage, aliases: list[str]) -> ScoreResult:
    text = prepared.message.normalized_text
    keyword_value, strong, threat, keyword_reasons = _keyword_score(text)
    time_value = time_score(case, prepared.posted_at_local)
    geo_value, geo_direct, geo_channel_only = geo_score_preloaded(case, prepared, aliases)
    source_value = 0.1 if prepared.message.url else 0.0
    total = round(time_value * 0.35 + geo_value * 0.3 + keyword_value * 0.25 + source_value, 3)
    generic_channel = _is_generic_monitor(prepared.channel)
    generic_threat = _contains_any(text, GENERIC_THREAT)
    priority = _priority(total, time_value, geo_direct, strong, threat, geo_channel_only)
    reasons = list(keyword_reasons)
    if (generic_channel or generic_threat) and not geo_direct:
        reasons.append("reject_generic_threat")
        priority = "NO DATA"
    if generic_channel and priority == "A":
        priority = "B"
    if threat and not strong and priority in {"A", "B"}:
        priority = "C" if geo_direct else "NO DATA"
    if geo_channel_only and not strong and priority == "B":
        priority = "C"
    if time_value <= 0:
        reasons.append("rejected_time")
    if geo_value <= 0:
        reasons.append("rejected_geo")
    if keyword_value <= 0 and "rejected_keyword" not in reasons and "rejected_noise" not in reasons:
        reasons.append("rejected_keyword")
        priority = "NO DATA"
    if keyword_value <= 0:
        priority = "NO DATA"
    if priority == "NO DATA" and "rejected_total" not in reasons:
        reasons.append("rejected_total")
    if geo_channel_only and priority == "A":
        priority = "B"
    return ScoreResult(time_value, geo_value, keyword_value, source_value, total, priority, reasons, geo_direct, strong, threat, generic_channel)


def score_message_for_case(session: Session, case: Case, message: Message) -> dict:
    channel = session.get(Channel, message.channel_id)
    places = session.query(MessagePlace).filter(MessagePlace.message_id == message.id).all()
    prepared = PreparedMessage(message, channel, places, set(), localize_message_time(message.posted_at))
    score = score_prepared_message(case, prepared, _case_aliases(case))
    return {
        "posted_at_local": prepared.posted_at_local,
        "time_score": score.time_score,
        "geo_score": score.geo_score,
        "keyword_score": score.keyword_score,
        "source_score": score.source_score,
        "total": score.total,
        "priority": score.priority,
        "reasons": score.reasons,
    }


def _candidate_query(session: Session, case: Case, aliases: list[str], start_utc: datetime, end_utc: datetime):
    cutoff = datetime.utcnow() - timedelta(minutes=get_settings().min_archive_delay_minutes)
    conditions = [Message.relevance_score > 0, Message.has_media.is_(True)]
    for alias in aliases[:8]:
        conditions.append(Message.normalized_text.like(f"%{alias}%"))
    channel_ids = []
    if aliases:
        channel_conditions = []
        for alias in aliases[:8]:
            channel_conditions.append(Channel.username.like(f"%{alias}%"))
            channel_conditions.append(Channel.title.like(f"%{alias}%"))
        channel_ids = [row[0] for row in session.execute(select(Channel.id).where(or_(*channel_conditions))).all()]
        if channel_ids:
            conditions.append(Message.channel_id.in_(channel_ids))
    return (
        session.query(Message)
        .filter(Message.posted_at >= start_utc, Message.posted_at <= end_utc, Message.posted_at <= cutoff, or_(*conditions))
        .order_by(Message.posted_at.asc())
    )


def candidates_for_case(session: Session, case: Case, limit: int | None = None) -> tuple[list[Message], datetime, datetime]:
    aliases = _case_aliases(case)
    start_utc, end_utc = evidence_window(case)
    query = _candidate_query(session, case, aliases, start_utc, end_utc)
    if limit:
        query = query.limit(limit)
    return query.all(), start_utc, end_utc


def _prepare_messages(session: Session, messages: list[Message]) -> dict[int, PreparedMessage]:
    if not messages:
        return {}
    message_ids = [m.id for m in messages]
    channel_ids = {m.channel_id for m in messages}
    channels = {c.id: c for c in session.query(Channel).filter(Channel.id.in_(channel_ids)).all()}
    places_by_message: dict[int, list[MessagePlace]] = {mid: [] for mid in message_ids}
    for place in session.query(MessagePlace).filter(MessagePlace.message_id.in_(message_ids)).all():
        places_by_message.setdefault(place.message_id, []).append(place)
    keywords_by_message: dict[int, set[str]] = {mid: set() for mid in message_ids}
    for keyword in session.query(MessageKeyword).filter(MessageKeyword.message_id.in_(message_ids)).all():
        keywords_by_message.setdefault(keyword.message_id, set()).add(keyword.category)
    return {
        m.id: PreparedMessage(
            message=m,
            channel=channels.get(m.channel_id),
            places=places_by_message.get(m.id, []),
            keyword_categories=keywords_by_message.get(m.id, set()),
            posted_at_local=localize_message_time(m.posted_at),
        )
        for m in messages
    }


def _accepted_sort_key(item: tuple[Message, ScoreResult]) -> tuple[int, float, datetime]:
    order = {"A": 0, "B": 1, "C": 2}
    return order.get(item[1].priority, 99), -item[1].total, item[0].posted_at


def match_cases(session: Session, progress: bool = True) -> dict:
    session.query(CaseMatch).delete()
    cases = session.query(Case).order_by(Case.id).all()
    created = 0
    stats = {"cases": len(cases), "matches": 0, "A": 0, "B": 0, "C": 0, "pending": 0}
    for index, case in enumerate(cases, start=1):
        aliases = _case_aliases(case)
        messages, _start_utc, _end_utc = candidates_for_case(session, case)
        prepared_by_id = _prepare_messages(session, messages)
        accepted: list[tuple[Message, ScoreResult]] = []
        rejected = {"rejected_time": 0, "rejected_geo": 0, "rejected_keyword": 0, "rejected_noise": 0, "rejected_total": 0, "reject_generic_threat": 0}
        seen: set[int] = set()
        for message in messages:
            dedupe_key = message.canonical_message_id or message.id
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            score = score_prepared_message(case, prepared_by_id[message.id], aliases)
            if score.priority in {"A", "B", "C"}:
                accepted.append((message, score))
            else:
                for reason in score.reasons:
                    if reason in rejected:
                        rejected[reason] += 1
        accepted.sort(key=_accepted_sort_key)
        selected = accepted[: get_settings().match_max_per_case]
        priority_counts = {"A": 0, "B": 0, "C": 0}
        for message, score in selected:
            priority_counts[score.priority] = priority_counts.get(score.priority, 0) + 1
            review_status = "auto_approved" if score.priority == "A" and score.geo_direct and score.strong_impact else "pending"
            session.add(
                CaseMatch(
                    case_id=case.id,
                    message_id=message.id,
                    match_type="telegram",
                    time_score=score.time_score,
                    geo_score=score.geo_score,
                    keyword_score=score.keyword_score,
                    source_score=score.source_score,
                    total_score=score.total,
                    priority=score.priority,
                    explanation=f"Fast match: time={score.time_score}, geo={score.geo_score}, keyword={score.keyword_score}",
                    review_status=review_status,
                    score_details_json=json.dumps(
                        {
                            "time_score": score.time_score,
                            "geo_score": score.geo_score,
                            "keyword_score": score.keyword_score,
                            "source_score": score.source_score,
                            "geo_direct": score.geo_direct,
                            "strong_impact": score.strong_impact,
                            "threat_only": score.threat_only,
                            "generic_channel": score.generic_channel,
                            "reasons": score.reasons,
                        },
                        ensure_ascii=False,
                    ),
                    reject_reason=";".join(score.reasons) if score.reasons else None,
                )
            )
            created += 1
            stats["matches"] += 1
            stats[score.priority] = stats.get(score.priority, 0) + 1
            if review_status == "pending":
                stats["pending"] += 1
        firms_added = 0
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
            created += 1
            firms_added += 1
        if not selected and not firms_added:
            session.add(CaseMatch(case_id=case.id, match_type="none", priority="NO DATA", explanation="NO DATA"))
            created += 1
        if progress:
            place = case.place_name or case.reference_text or "unknown"
            print(
                f"Case {index}/{len(cases)} {place}: candidates={len(messages)} accepted={len(selected)} "
                f"A={priority_counts.get('A', 0)} B={priority_counts.get('B', 0)} C={priority_counts.get('C', 0)} "
                + " ".join(f"{key}={value}" for key, value in rejected.items())
            )
    print(f"Created {created} matches.")
    return stats


def legacy_match_cases(session: Session) -> int:
    # Kept as a compatibility alias; the old O(cases * messages) implementation was intentionally removed.
    return match_cases(session, progress=True)
