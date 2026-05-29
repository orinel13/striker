from __future__ import annotations

from datetime import datetime

from docx import Document

from app.batches import create_batch
from app.documents import report_exporter
from app.documents.report_exporter import export_report
from app.models import Case, CaseMatch, Channel, Message
from app.telegram.normalizer import normalize_text, text_sha256


def _approved(session, batch_id: int, place: str, text: str) -> None:
    channel = session.query(Channel).first()
    if not channel:
        channel = Channel(username="test_channel", title="Test Channel")
        session.add(channel)
        session.flush()
    case = Case(batch_id=batch_id, raw_text=text, place_name=place)
    session.add(case)
    session.flush()
    norm = normalize_text(text)
    message = Message(
        channel_id=channel.id,
        tg_message_id=session.query(Message).count() + 1,
        posted_at=datetime(2026, 5, 28, 18, 0),
        collected_at=datetime(2026, 5, 28, 18, 0),
        text=text,
        normalized_text=norm,
        text_hash=text_sha256(norm),
        url=f"https://t.me/test_channel/{case.id}",
    )
    session.add(message)
    session.flush()
    session.add(CaseMatch(case_id=case.id, message_id=message.id, match_type="telegram", priority="B", total_score=0.8, explanation="ok", review_status="approved"))


def test_export_report_is_batch_scoped(session, tmp_path, monkeypatch):
    monkeypatch.setattr(report_exporter, "_export_dir", lambda: tmp_path)
    old = create_batch(session, source_filename="old.docx")
    current = create_batch(session, source_filename="current.docx")
    _approved(session, old.id, "Славянск", "old batch text")
    _approved(session, current.id, "Краматорск", "current batch text")
    session.commit()
    export = export_report(session, batch_id=current.id, progress=None)
    text = "\n".join(p.text for p in Document(export.docx_path).paragraphs)
    assert "current batch text" in text
    assert "Краматорск" in text
    assert "old batch text" not in text
    assert "Славянск" not in text
