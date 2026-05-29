from __future__ import annotations

import logging
import json
import time
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.documents.docx_importer import import_docx
from app.documents.report_exporter import export_report
from app.firms.client import fetch_firms_for_all_cases
from app.matching.case_matcher import match_cases
from app.matching.evidence import render_evidence
from app.models import Job
from app.telegram.collector import collect_once

logger = logging.getLogger(__name__)


def create_job(session: Session, kind: str, input_path: str | None = None, params: dict | None = None) -> Job:
    job = Job(
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
            )
            session.commit()
            _update(session, job, 30, "fetch-firms")
            fetch_firms_for_all_cases(session)
            session.commit()
            _update(session, job, 55, "match-cases")
            match_cases(session)
            session.commit()
            _update(session, job, 75, "render-evidence")
            render_evidence(session)
            session.commit()
            _update(session, job, 90, "export-report")
            export = export_report(session, job_id=job.id, source_docx=job.input_path)
            job.output_path = export.zip_path
        elif job.kind == "fetch-firms":
            fetch_firms_for_all_cases(session)
        elif job.kind == "match-cases":
            match_cases(session)
        elif job.kind == "render-evidence":
            render_evidence(session)
        elif job.kind == "export-report":
            export = export_report(session, job_id=job.id)
            job.output_path = export.zip_path
        elif job.kind == "collect-once":
            import asyncio

            asyncio.run(collect_once())
        else:
            raise RuntimeError(f"Unknown job kind: {job.kind}")
        job.progress = 100
        job.current_step = "done"
        job.status = "done"
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
