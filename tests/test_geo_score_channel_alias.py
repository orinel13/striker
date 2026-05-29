from datetime import datetime, timedelta

from sqlalchemy import select

from app.matching.case_matcher import geo_score, match_cases
from app.models import Case, CaseMatch, Channel, Message
from app.telegram.normalizer import normalize_text, text_sha256


def test_channel_city_alias_gives_indirect_geo_score_and_caps_priority(session):
    channel = Channel(username="kramatorsk_now", title="Краматорск сейчас")
    session.add(channel)
    session.flush()
    case = Case(
        raw_text="Краматорск 10:00",
        place_name="Краматорск",
        lat=48.72,
        lon=37.55,
        time_window_start=datetime(2024, 5, 29, 10, 0),
        time_window_end=datetime(2024, 5, 29, 11, 0),
    )
    text = "громко, взрыв"
    norm = normalize_text(text)
    message = Message(
        channel_id=channel.id,
        tg_message_id=1,
        posted_at=datetime(2024, 5, 29, 7, 30),
        collected_at=datetime.utcnow() - timedelta(days=1),
        text=text,
        normalized_text=norm,
        text_hash=text_sha256(norm),
        url="https://t.me/kramatorsk_now/1",
    )
    session.add_all([case, message])
    session.commit()
    assert geo_score(session, case, message) == 0.45
    match_cases(session)
    matches = session.execute(select(CaseMatch).where(CaseMatch.match_type == "telegram")).scalars().all()
    assert len(matches) == 1
    assert matches[0].priority == "B"

