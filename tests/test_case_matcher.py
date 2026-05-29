from datetime import datetime, timedelta

from sqlalchemy import select

from app.matching.case_matcher import match_cases
from app.models import Case, CaseMatch, Channel, Message, MessagePlace
from app.telegram.normalizer import normalize_text, text_sha256


def test_case_matcher_creates_priority_a(session):
    channel = Channel(username="test")
    session.add(channel)
    session.flush()
    case = Case(
        raw_text="12.05.2024 03:00 Київ",
        event_date=datetime(2024, 5, 12).date(),
        event_time_local="03:00",
        time_window_start=datetime(2024, 5, 12, 2),
        time_window_end=datetime(2024, 5, 12, 4),
        place_name="київ",
        lat=50.45,
        lon=30.52,
        radius_km=15,
    )
    text = "ракета удар пожежа Київ"
    norm = normalize_text(text)
    msg = Message(
        channel_id=channel.id,
        tg_message_id=1,
        posted_at=datetime(2024, 5, 12, 0, 10),
        collected_at=datetime.utcnow() - timedelta(days=1),
        text=text,
        normalized_text=norm,
        text_hash=text_sha256(norm),
        url="https://t.me/test/1",
    )
    session.add_all([case, msg])
    session.flush()
    session.add(MessagePlace(message_id=msg.id, raw_mention="Київ", lat=50.45, lon=30.52, confidence=1.0))
    session.commit()
    match_cases(session)
    matches = session.execute(select(CaseMatch)).scalars().all()
    assert matches[0].priority == "A"


def test_archive_delay_filters_recent_messages(session, monkeypatch):
    channel = Channel(username="test")
    session.add(channel)
    session.flush()
    case = Case(raw_text="today", event_date=datetime.utcnow().date(), time_window_start=datetime.utcnow() - timedelta(hours=1), time_window_end=datetime.utcnow() + timedelta(hours=1))
    text = "ракета удар"
    norm = normalize_text(text)
    msg = Message(
        channel_id=channel.id,
        tg_message_id=1,
        posted_at=datetime.utcnow(),
        collected_at=datetime.utcnow(),
        text=text,
        normalized_text=norm,
        text_hash=text_sha256(norm),
    )
    session.add_all([case, msg])
    session.commit()
    match_cases(session)
    matches = session.execute(select(CaseMatch)).scalars().all()
    assert matches[0].priority == "NO DATA"
