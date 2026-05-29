from __future__ import annotations

from datetime import datetime

from app.jobs import create_job, run_job
from app.models import Case, CaseBatch


def test_process_docx_stops_at_review_required_without_export_or_evidence(session, tmp_path, monkeypatch):
    source = tmp_path / "strikes.docx"
    source.write_bytes(b"fake")

    def fake_import_docx(session_arg, path, **kwargs):
        case = Case(batch_id=kwargs["batch_id"], raw_text="case", place_name="Краматорск")
        session_arg.add(case)
        session_arg.flush()
        return [case]

    monkeypatch.setattr("app.jobs.import_docx", fake_import_docx)
    monkeypatch.setattr("app.jobs.fetch_firms_for_all_cases", lambda session_arg: 0)
    monkeypatch.setattr("app.jobs.match_cases", lambda session_arg, batch_id=None: {"matches": 2, "pending": 1, "auto_approved": 1})
    monkeypatch.setattr("app.jobs.render_evidence", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("render_evidence should not run")))
    monkeypatch.setattr("app.jobs.export_report", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("export_report should not run")))

    job = create_job(session, "process-docx", str(source), params={"document_date": "2026-05-28"})
    session.commit()
    run_job(session, job)
    batch = session.query(CaseBatch).one()
    assert job.status == "review_required"
    assert "Review required" in (job.current_step or "")
    assert batch.status == "review_required"
    assert session.query(Case).count() == 1


def test_export_report_job_creates_text_only_report_after_approval(session, tmp_path, monkeypatch):
    from app.batches import create_batch
    from app.models import CaseMatch, Channel, Message
    from app.telegram.normalizer import normalize_text, text_sha256

    monkeypatch.setattr("app.documents.report_exporter._export_dir", lambda: tmp_path)
    batch = create_batch(session, source_filename="today.docx")
    channel = Channel(username="kramatorsk", title="Kramatorsk")
    session.add(channel)
    session.flush()
    case = Case(batch_id=batch.id, raw_text="case", place_name="Краматорск")
    session.add(case)
    session.flush()
    norm = normalize_text("approved text")
    msg = Message(channel_id=channel.id, tg_message_id=1, posted_at=datetime(2026, 5, 28, 18, 0), collected_at=datetime(2026, 5, 28, 18, 0), text="approved text", normalized_text=norm, text_hash=text_sha256(norm), url="https://t.me/kramatorsk/1")
    session.add(msg)
    session.flush()
    session.add(CaseMatch(case_id=case.id, message_id=msg.id, match_type="telegram", priority="B", total_score=0.8, explanation="ok", review_status="approved"))
    job = create_job(session, "export-report", params={"text_only": True}, batch_id=batch.id)
    session.commit()
    run_job(session, job)
    assert job.status == "done"
    assert job.output_path and job.output_path.endswith("evidence.zip")
    assert session.get(CaseBatch, batch.id).status == "completed"
