from __future__ import annotations

from datetime import datetime, timedelta

from app.batches import create_batch, delete_batch, get_current_batch
from app.matching.case_matcher import match_cases
from app.models import Case, CaseMatch, Channel, Message
from app.telegram.collector import prune_archive
from app.telegram.normalizer import normalize_text, text_sha256


def _message(session, channel, posted_at: datetime) -> Message:
    norm = normalize_text("archive message")
    msg = Message(
        channel_id=channel.id,
        tg_message_id=int(posted_at.timestamp()),
        posted_at=posted_at,
        collected_at=posted_at,
        text="archive message",
        normalized_text=norm,
        text_hash=text_sha256(norm),
    )
    session.add(msg)
    session.flush()
    return msg


def test_batch_delete_keeps_telegram_archive(session):
    batch = create_batch(session, source_filename="today.docx")
    channel = Channel(username="kramatorsk", title="Kramatorsk")
    session.add(channel)
    session.flush()
    msg = _message(session, channel, datetime.utcnow())
    case = Case(batch_id=batch.id, raw_text="case", place_name="Краматорск")
    session.add(case)
    session.flush()
    session.add(CaseMatch(case_id=case.id, message_id=msg.id, match_type="telegram", priority="B", explanation="x"))
    session.commit()
    delete_batch(session, batch.id, delete_files=False)
    session.commit()
    assert session.query(Case).count() == 0
    assert session.query(CaseMatch).count() == 0
    assert session.query(Message).count() == 1
    assert session.query(Channel).count() == 1


def test_match_cases_only_clears_selected_batch(session):
    b1 = create_batch(session, source_filename="one.docx")
    b2 = create_batch(session, source_filename="two.docx")
    c1 = Case(batch_id=b1.id, raw_text="case1", place_name="Краматорск")
    c2 = Case(batch_id=b2.id, raw_text="case2", place_name="Славянск")
    session.add_all([c1, c2])
    session.flush()
    session.add_all(
        [
            CaseMatch(case_id=c1.id, match_type="none", priority="NO DATA", explanation="old b1"),
            CaseMatch(case_id=c2.id, match_type="none", priority="NO DATA", explanation="old b2"),
        ]
    )
    session.commit()
    match_cases(session, batch_id=b1.id, progress=False)
    session.commit()
    texts = [m.explanation for m in session.query(CaseMatch).all()]
    assert "old b1" not in texts
    assert "old b2" in texts


def test_current_batch_is_latest_active(session):
    old = create_batch(session, source_filename="old.docx")
    new = create_batch(session, source_filename="new.docx")
    assert get_current_batch(session).id == new.id
    old.status = "archived"
    session.commit()
    assert get_current_batch(session).id == new.id


def test_prune_archive_does_not_delete_batches_or_cases(session):
    batch = create_batch(session, source_filename="today.docx")
    case = Case(batch_id=batch.id, raw_text="case", place_name="Краматорск")
    channel = Channel(username="archive", title="Archive")
    session.add_all([case, channel])
    session.flush()
    _message(session, channel, datetime.utcnow() - timedelta(days=10))
    session.commit()
    removed = prune_archive(session, days=3, vacuum=False)
    session.commit()
    assert removed == 1
    assert session.query(Message).count() == 0
    assert session.query(Case).count() == 1
    assert get_current_batch(session).id == batch.id
