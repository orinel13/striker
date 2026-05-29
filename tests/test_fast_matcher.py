from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from app.matching.case_matcher import localize_message_time, match_cases
from app.models import Case, CaseMatch, Channel, Message
from app.telegram.normalizer import normalize_text, text_sha256


def _message(session, channel, idx: int, posted_at: datetime, text: str, relevance: float = 0.0) -> Message:
    normalized = normalize_text(text)
    message = Message(
        channel_id=channel.id,
        tg_message_id=idx,
        posted_at=posted_at,
        collected_at=datetime.utcnow() - timedelta(days=1),
        text=text,
        normalized_text=normalized,
        text_hash=text_sha256(normalized),
        url=f"https://t.me/{channel.username}/{idx}",
        relevance_score=relevance,
    )
    session.add(message)
    return message


def test_fast_matcher_accepts_threat_and_rejects_noise(session):
    channel = Channel(username="slav_kramatorskDonbass", title="Славянск Краматорск")
    session.add(channel)
    session.flush()
    case = Case(
        raw_text="Славянск ночь",
        place_name="Славянск",
        event_date=datetime(2026, 5, 29).date(),
        time_window_start=datetime(2026, 5, 28, 23, 0),
        time_window_end=datetime(2026, 5, 29, 0, 0),
    )
    session.add(case)
    session.flush()
    posted_utc = datetime.utcnow() - timedelta(hours=3)
    _message(session, channel, 1, posted_utc, "Славянск КАБ в сторону города")
    _message(session, channel, 2, posted_utc, "Стрижки женские... Славянск")
    posted_local = localize_message_time(posted_utc)
    case.time_window_start = posted_local - timedelta(hours=1)
    case.time_window_end = posted_local + timedelta(minutes=30)
    session.commit()
    match_cases(session, progress=False)
    matches = session.execute(select(CaseMatch).where(CaseMatch.match_type == "telegram")).scalars().all()
    assert len(matches) == 1
    assert matches[0].priority in {"B", "C"}


def test_fast_matcher_accepts_kramatorsk_channel_alias(session):
    channel = Channel(username="kramatorskiy_pishet", title="Краматорський канал")
    session.add(channel)
    session.flush()
    case = Case(
        raw_text="Краматорск",
        place_name="Краматорск",
        time_window_start=localize_message_time(datetime.utcnow() - timedelta(hours=2)) - timedelta(hours=1),
        time_window_end=localize_message_time(datetime.utcnow() - timedelta(hours=2)) + timedelta(hours=1),
    )
    session.add(case)
    session.flush()
    _message(session, channel, 1, datetime.utcnow() - timedelta(hours=2), "У Краматорській громаді пошкоджено будівлю", relevance=0.1)
    session.commit()
    match_cases(session, progress=False)
    matches = session.execute(select(CaseMatch).where(CaseMatch.match_type == "telegram")).scalars().all()
    assert len(matches) == 1
    assert matches[0].priority == "B"


def test_fast_matcher_handles_thousands_of_noise_messages(session):
    channel = Channel(username="kramatorsk_now", title="Краматорск")
    session.add(channel)
    session.flush()
    case = Case(
        raw_text="Краматорск",
        place_name="Краматорск",
        time_window_start=localize_message_time(datetime.utcnow() - timedelta(hours=2)) - timedelta(hours=1),
        time_window_end=localize_message_time(datetime.utcnow() - timedelta(hours=2)) + timedelta(hours=1),
    )
    session.add(case)
    session.flush()
    for idx in range(5000):
        _message(session, channel, idx + 1, datetime.utcnow() - timedelta(hours=2), f"маникюр доставка вакансия {idx}")
    _message(session, channel, 6001, datetime.utcnow() - timedelta(hours=2), "Краматорск взрыв, пошкоджено будівлю")
    _message(session, channel, 6002, datetime.utcnow() - timedelta(hours=2), "громко, вибух", relevance=0.2)
    session.commit()
    match_cases(session, progress=False)
    matches = session.execute(select(CaseMatch).where(CaseMatch.match_type == "telegram")).scalars().all()
    assert len(matches) == 2
