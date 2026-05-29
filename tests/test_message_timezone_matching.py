from datetime import datetime, timedelta

from sqlalchemy import select

from app.matching.case_matcher import match_cases
from app.models import Case, CaseMatch, Channel, Message
from app.telegram.normalizer import normalize_text, text_sha256


def test_utc_message_timestamp_matches_kyiv_case_window(session):
    channel = Channel(username="kyiv_channel", title="Київ")
    session.add(channel)
    session.flush()
    case = Case(
        raw_text="29.05.2024 10:00 Київ",
        event_date=datetime(2024, 5, 29).date(),
        time_window_start=datetime(2024, 5, 29, 10, 0),
        time_window_end=datetime(2024, 5, 29, 11, 0),
        place_name="Київ",
    )
    text = "вибух Київ пожежа"
    norm = normalize_text(text)
    message = Message(
        channel_id=channel.id,
        tg_message_id=1,
        posted_at=datetime(2024, 5, 29, 7, 30),
        collected_at=datetime.utcnow() - timedelta(days=1),
        text=text,
        normalized_text=norm,
        text_hash=text_sha256(norm),
        url="https://t.me/kyiv_channel/1",
    )
    session.add_all([case, message])
    session.commit()
    match_cases(session)
    matches = session.execute(select(CaseMatch).where(CaseMatch.match_type == "telegram")).scalars().all()
    assert len(matches) == 1
    assert matches[0].time_score == 1.0

