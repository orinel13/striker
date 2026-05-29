from __future__ import annotations

import logging
import json
import time
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.batches import approved_publications_count, create_batch, current_batch_id, update_batch_counts
from app.config import get_settings
from app.documents.docx_importer import import_docx
from app.documents.report_exporter import export_report
from app.firms.client import fetch_firms_for_all_cases
from app.matching.case_matcher import match_cases
from app.matching.evidence import render_evidence
from app.models import CaseBatch, Job
from app.telegram.collector import collect_once

logger = logging.getLogger(__name__)


def create_job(session: Session, kind: str, input_path: str | None = None, params: dict | None = None, batch_id: int | None = None) -> Job:
    job = Job(
        batch_id=batch_id,
        kind=kind,
        input_path=input_path,
        params_json=json.dumps(params, ensure_ascii=False) if params else None,
        status="queued",
        progress=0,
    )
    session.add(job)
    session.flush()
    return job


def _update(session: Session, job: Job, progress: int, step: str) -> None:
    job.progress = progress
    job.current_step = step
    session.commit()


def run_job(session: Session, job: Job) -> None:
    job.status = "running"
    job.started_at = datetime.utcnow()
    job.error = None
    session.commit()
    final_status = "done"
    final_step = "done"
    try:
        if job.kind in {"process-docx", "import-docx"}:
            if not job.input_path or not Path(job.input_path).exists():
                raise RuntimeError("Job input .docx does not exist")
            params = json.loads(job.params_json or "{}")
            document_date = date.fromisoformat(params["document_date"]) if params.get("document_date") else None
            default_year = int(params["default_year"]) if params.get("default_year") else None
            period_start = date.fromisoformat(params["period_start"]) if params.get("period_start") else None
            period_end = date.fromisoformat(params["period_end"]) if params.get("period_end") else None
            night_mode = bool(params.get("night_mode"))
            rollover_hour = int(params.get("rollover_hour", 12))
            if job.batch_id:
                batch_id = job.batch_id
            else:
                batch = create_batch(
                    session,
                    source_filename=Path(job.input_path).name,
                    original_path=job.input_path,
                    title=params.get("batch_title"),
                    document_date=document_date,
                    period_start=period_start,
                    period_end=period_end,
                    night_mode=night_mode,
                    rollover_hour=rollover_hour,
                    activate=bool(params.get("activate", True)),
                    archive_previous=bool(params.get("archive_previous", get_settings().archive_previous_batches_on_upload)),
                )
                job.batch_id = batch.id
                batch_id = batch.id
                session.commit()
            _update(session, job, 10, "import-docx")
            import_docx(
                session,
                job.input_path,
                document_date=document_date,
                default_year=default_year,
                period_start=period_start,
                period_end=period_end,
                night_mode=night_mode,
                rollover_hour=rollover_hour,
                batch_id=batch_id,
            )
            session.commit()
            _update(session, job, 30, "fetch-firms")
            fetch_firms_for_all_cases(session)
            session.commit()
            _update(session, job, 55, "match-cases")
            stats = match_cases(session, batch_id=batch_id)
            update_batch_counts(session, batch_id)
            batch = session.get(CaseBatch, batch_id)
            if batch:
                batch.status = "review_required"
            final_status = "review_required"
            final_step = f"Review required: {stats['pending']} pending, {stats.get('auto_approved', 0)} auto-approved"
            job.current_step = final_step
            session.commit()
        elif job.kind == "fetch-firms":
            fetch_firms_for_all_cases(session)
        elif job.kind == "match-cases":
            params = json.loads(job.params_json or "{}")
            batch_id = current_batch_id(session, int(params["batch_id"]) if params.get("batch_id") else job.batch_id)
            stats = match_cases(session, batch_id=batch_id, all_batches=bool(params.get("all_batches")))
            job.current_step = f"matched: {stats['matches']} telegram matches, {stats['pending']} pending review"
        elif job.kind == "render-evidence":
            params = json.loads(job.params_json or "{}")
            batch_id = current_batch_id(session, int(params["batch_id"]) if params.get("batch_id") else job.batch_id)
            render_evidence(session, batch_id=batch_id, include_pending=bool(params.get("include_pending")))
        elif job.kind == "export-report":
            params = json.loads(job.params_json or "{}")
            batch_id = current_batch_id(session, int(params["batch_id"]) if params.get("batch_id") else job.batch_id)
            if approved_publications_count(session, batch_id) <= 0:
                raise RuntimeError("No approved publications for report")
            export = export_report(
                session,
                job_id=job.id,
                batch_id=batch_id,
                text_only=bool(params.get("text_only", True)),
                with_local_cards=bool(params.get("with_local_cards", False)),
                external_screenshots=bool(params.get("external_screenshots", False)),
                include_pending=bool(params.get("include_pending", False)),
            )
            job.output_path = export.zip_path
            if batch_id:
                batch = session.get(CaseBatch, batch_id)
                if batch:
                    batch.status = "completed"
                    update_batch_counts(session, batch_id)
        elif job.kind == "collect-once":
            import asyncio

            asyncio.run(collect_once())
        else:
            raise RuntimeError(f"Unknown job kind: {job.kind}")
        job.progress = 100
        job.current_step = final_step
        job.status = final_status
        job.finished_at = datetime.utcnow()
        session.commit()
    except Exception as exc:
        session.rollback()
        job = session.get(Job, job.id)
        if job:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.utcnow()
            session.commit()
        logger.exception("Job failed: %s", exc)


def worker_loop(session_factory) -> None:
    settings = get_settings()
    while True:
        with session_factory() as session:
            job = session.query(Job).filter(Job.status == "queued").order_by(Job.created_at).first()
            if job:
                run_job(session, job)
        time.sleep(settings.job_poll_seconds)
