from __future__ import annotations

import zipfile
from datetime import datetime

from docx import Document

from app.batches import create_batch
from app.documents import report_exporter
from app.documents.report_exporter import export_report
from app.models import Case, CaseMatch, Channel, Message
from app.telegram.normalizer import normalize_text, text_sha256


def _message(session, channel, tg_id: int, text: str, url: str, posted_at: datetime) -> Message:
    norm = normalize_text(text)
    message = Message(
        channel_id=channel.id,
        tg_message_id=tg_id,
        posted_at=posted_at,
        collected_at=posted_at,
        text=text,
        normalized_text=norm,
        text_hash=text_sha256(norm),
        url=url,
    )
    session.add(message)
    session.flush()
    return message


def test_text_only_report_content_and_no_images(session, tmp_path, monkeypatch):
    monkeypatch.setattr(report_exporter, "_export_dir", lambda: tmp_path)
    monkeypatch.setattr(report_exporter, "screenshot_message", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("external screenshot called")))
    monkeypatch.setattr(report_exporter, "render_evidence_card_png", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("local card called")))
    batch = create_batch(session, source_filename="strikes.docx")
    channel = Channel(username="izyum_live_news", title="Ізюм live 🇺🇦")
    session.add(channel)
    session.flush()
    case = Case(batch_id=batch.id, raw_text="case", place_name="Ізюм")
    session.add(case)
    session.flush()
    text = "Ударний БПЛА на Ізюм⚠️\n\n✅ Ізюм Live - підписатись\n🔵 Надіслати новину"
    msg = _message(session, channel, 111467, text, "https://t.me/izyum_live_news/111467", datetime(2026, 5, 28, 18, 27))
    session.add(
        CaseMatch(
            case_id=case.id,
            message_id=msg.id,
            match_type="telegram",
            priority="B",
            total_score=0.8,
            explanation="approved",
            review_status="approved",
        )
    )
    pending = _message(session, channel, 111468, "pending text", "https://t.me/izyum_live_news/111468", datetime(2026, 5, 28, 18, 30))
    session.add(
        CaseMatch(
            case_id=case.id,
            message_id=pending.id,
            match_type="telegram",
            priority="C",
            total_score=0.6,
            explanation="pending",
            review_status="pending",
        )
    )
    session.commit()
    export = export_report(session, batch_id=batch.id, progress=None)
    doc = Document(export.docx_path)
    body = "\n".join(p.text for p in doc.paragraphs)
    assert "Ізюм" in body
    assert "Публикация №1" in body
    assert "OSINT" in body
    assert "28.05.2026 г." in body
    assert "Источник: Telegram, Ізюм live 🇺🇦 (@izyum_live_news)" in body
    assert "Время публикации: 21:27" in body
    assert "https://t.me/izyum_live_news/111467" in body
    assert "Подтверждающий материал: фотоматериал." in body
    assert "Ударний БПЛА на Ізюм⚠️" in body
    assert "pending text" not in body
    assert "NO DATA" not in body
    assert "score_details" not in body
    assert not any("image" in rel.reltype for rel in doc.part.rels.values())
    with zipfile.ZipFile(export.zip_path) as zf:
        names = zf.namelist()
    assert "report.docx" in names
    assert "report.html" in names
    assert not any(name.endswith(".png") for name in names)


def test_export_report_requires_approved_publications(session, tmp_path, monkeypatch):
    monkeypatch.setattr(report_exporter, "_export_dir", lambda: tmp_path)
    batch = create_batch(session, source_filename="empty.docx")
    case = Case(batch_id=batch.id, raw_text="case", place_name="Краматорск")
    session.add(case)
    session.commit()
    try:
        export_report(session, batch_id=batch.id, progress=None)
    except RuntimeError as exc:
        assert "No approved publications for report" in str(exc)
    else:
        raise AssertionError("export_report should fail without approved publications")
