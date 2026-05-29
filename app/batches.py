from __future__ import annotations

import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Case, CaseBatch, CaseMatch, EvidenceFile, Export, Job


CURRENT_STATUSES = {"active", "review_required", "completed"}


def get_current_batch(session: Session) -> CaseBatch | None:
    return (
        session.query(CaseBatch)
        .filter(CaseBatch.status.in_(CURRENT_STATUSES))
        .order_by(CaseBatch.updated_at.desc(), CaseBatch.id.desc())
        .first()
    )


def current_batch_id(session: Session, batch_id: int | None = None) -> int | None:
    if batch_id:
        return batch_id
    batch = get_current_batch(session)
    return batch.id if batch else None


def create_batch(
    session: Session,
    source_filename: str | None = None,
    original_path: str | None = None,
    title: str | None = None,
    document_date: date | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    night_mode: bool = False,
    rollover_hour: int | None = 12,
    activate: bool = True,
    archive_previous: bool = False,
) -> CaseBatch:
    if archive_previous:
        for batch in session.query(CaseBatch).filter(CaseBatch.status.in_(CURRENT_STATUSES)).all():
            batch.status = "archived"
    batch = CaseBatch(
        source_filename=source_filename,
        original_path=original_path,
        title=title or source_filename or "Imported document",
        document_date=document_date,
        period_start=period_start,
        period_end=period_end,
        night_mode=night_mode,
        rollover_hour=rollover_hour,
        status="active" if activate else "archived",
    )
    session.add(batch)
    session.flush()
    return batch


def activate_batch(session: Session, batch_id: int, archive_previous: bool = False) -> CaseBatch:
    batch = session.get(CaseBatch, batch_id)
    if not batch:
        raise ValueError(f"Batch not found: {batch_id}")
    if archive_previous:
        for other in session.query(CaseBatch).filter(CaseBatch.id != batch_id, CaseBatch.status.in_(CURRENT_STATUSES)).all():
            other.status = "archived"
    batch.status = "active"
    batch.updated_at = datetime.utcnow()
    return batch


def archive_batch(session: Session, batch_id: int) -> CaseBatch:
    batch = session.get(CaseBatch, batch_id)
    if not batch:
        raise ValueError(f"Batch not found: {batch_id}")
    batch.status = "archived"
    batch.updated_at = datetime.utcnow()
    return batch


def update_batch_counts(session: Session, batch_id: int) -> None:
    batch = session.get(CaseBatch, batch_id)
    if not batch:
        return
    case_ids = [row[0] for row in session.query(Case.id).filter(Case.batch_id == batch_id).all()]
    batch.cases_count = len(case_ids)
    if case_ids:
        batch.matches_count = session.query(func.count(CaseMatch.id)).filter(CaseMatch.case_id.in_(case_ids), CaseMatch.match_type == "telegram").scalar() or 0
        batch.approved_count = (
            session.query(func.count(CaseMatch.id))
            .filter(CaseMatch.case_id.in_(case_ids), CaseMatch.review_status.in_(["approved", "auto_approved"]), CaseMatch.message_id.isnot(None))
            .scalar()
            or 0
        )
        batch.pending_count = (
            session.query(func.count(CaseMatch.id))
            .filter(CaseMatch.case_id.in_(case_ids), CaseMatch.review_status == "pending", CaseMatch.message_id.isnot(None))
            .scalar()
            or 0
        )
    else:
        batch.matches_count = 0
        batch.approved_count = 0
        batch.pending_count = 0
    batch.updated_at = datetime.utcnow()


def approved_publications_count(session: Session, batch_id: int | None) -> int:
    query = session.query(func.count(CaseMatch.id)).join(Case, Case.id == CaseMatch.case_id)
    if batch_id is not None:
        query = query.filter(Case.batch_id == batch_id)
    return (
        query.filter(CaseMatch.match_type == "telegram", CaseMatch.message_id.isnot(None), CaseMatch.review_status.in_(["approved", "auto_approved"]))
        .scalar()
        or 0
    )


def delete_batch(session: Session, batch_id: int, delete_files: bool = True) -> None:
    case_ids = [row[0] for row in session.query(Case.id).filter(Case.batch_id == batch_id).all()]
    export_paths: list[Path] = []
    for export in session.query(Export).filter(Export.batch_id == batch_id).all():
        for value in [export.docx_path, export.html_path, export.zip_path]:
            if value:
                export_paths.append(Path(value).parent)
        session.delete(export)
    if case_ids:
        session.query(CaseMatch).filter(CaseMatch.case_id.in_(case_ids)).delete(synchronize_session=False)
        session.query(EvidenceFile).filter(EvidenceFile.batch_id == batch_id).delete(synchronize_session=False)
        session.query(Case).filter(Case.id.in_(case_ids)).delete(synchronize_session=False)
    session.query(Job).filter(Job.batch_id == batch_id).delete(synchronize_session=False)
    batch = session.get(CaseBatch, batch_id)
    if batch:
        session.delete(batch)
    if delete_files:
        for root in set(export_paths):
            if root.name and root.parent == Path("data/exports"):
                shutil.rmtree(root, ignore_errors=True)


def cleanup_batches(session: Session, archive_older_than_days: int | None = None, delete_archived: bool = False) -> int:
    changed = 0
    if archive_older_than_days is not None:
        cutoff = datetime.utcnow() - timedelta(days=archive_older_than_days)
        for batch in session.query(CaseBatch).filter(CaseBatch.created_at < cutoff, CaseBatch.status.in_(CURRENT_STATUSES)).all():
            batch.status = "archived"
            changed += 1
    if delete_archived:
        ids = [row[0] for row in session.query(CaseBatch.id).filter(CaseBatch.status == "archived").all()]
        for batch_id in ids:
            delete_batch(session, batch_id)
            changed += 1
    return changed
