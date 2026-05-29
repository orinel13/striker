from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from app.matching.case_matcher import localize_message_time, match_cases
from app.models import Case, CaseMatch, Channel, Message
from app.telegram.normalizer import normalize_text, text_sha256


def _add_message(session, channel, text: str, hours_ago: int = 2, relevance: float = 0.2) -> Message:
    posted = datetime.utcnow() - timedelta(hours=hours_ago)
    norm = normalize_text(text)
    msg = Message(
        channel_id=channel.id,
        tg_message_id=abs(hash(text)) % 100000,
        posted_at=posted,
        collected_at=posted,
        text=text,
        normalized_text=norm,
        text_hash=text_sha256(norm),
        url=f"https://t.me/{channel.username}/1",
        relevance_score=relevance,
    )
    session.add(msg)
    return msg


def _case_for(session, place: str, posted_utc: datetime | None = None) -> Case:
    posted_utc = posted_utc or (datetime.utcnow() - timedelta(hours=2))
    local = localize_message_time(posted_utc)
    case = Case(raw_text=place, place_name=place, time_window_start=local - timedelta(hours=1), time_window_end=local + timedelta(hours=1))
    session.add(case)
    return case


def _telegram_matches(session):
    return session.execute(select(CaseMatch).where(CaseMatch.match_type == "telegram")).scalars().all()


def test_chernihiv_lyceum_noise_rejected(session):
    channel = Channel(username="chernihiv_news", title="Чернігів")
    session.add(channel)
    session.flush()
    _case_for(session, "Чернигов")
    _add_message(session, channel, "У Чернігові відкрили підземний навчальний ліцей")
    session.commit()
    match_cases(session, progress=False)
    assert _telegram_matches(session) == []


def test_izyum_silicone_blogger_noise_rejected(session):
    channel = Channel(username="izyum_city", title="Ізюм")
    session.add(channel)
    session.flush()
    _case_for(session, "Изюм")
    _add_message(session, channel, "Блогерка показала силікон та косметолога в Ізюмі")
    session.commit()
    match_cases(session, progress=False)
    assert _telegram_matches(session) == []


def test_generic_war_monitor_threat_without_place_rejected(session):
    channel = Channel(username="war_monitor", title="war_monitor")
    session.add(channel)
    session.flush()
    _case_for(session, "Одесса")
    _add_message(session, channel, "Ймовірно готується масований ракетний удар")
    session.commit()
    match_cases(session, progress=False)
    assert _telegram_matches(session) == []


def test_sloviansk_threat_is_not_a(session):
    channel = Channel(username="sloviansk_news", title="Слов'янськ")
    session.add(channel)
    session.flush()
    _case_for(session, "Славянск")
    _add_message(session, channel, "КАБи курсом на Слов'янськ")
    session.commit()
    match_cases(session, progress=False)
    matches = _telegram_matches(session)
    assert len(matches) == 1
    assert matches[0].priority in {"B", "C"}
    assert matches[0].priority != "A"


def test_kramatorsk_strong_impact_direct_alias_accepted(session):
    channel = Channel(username="kramatorsk_news", title="Краматорск")
    session.add(channel)
    session.flush()
    _case_for(session, "Краматорск")
    _add_message(session, channel, "Краматорск: обстріл, пошкоджено будинки")
    session.commit()
    match_cases(session, progress=False)
    matches = _telegram_matches(session)
    assert len(matches) == 1
    assert matches[0].priority in {"A", "B"}

