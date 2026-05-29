from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.jobs import create_job
from sqlalchemy import func

from app.models import Case, CaseMatch, Channel, ChannelCandidate, Export, Job, Message
from app.security import (
    ensure_csrf,
    new_csrf_token,
    require_api_auth,
    sanitize_filename,
    validate_docx_upload,
    verify_password,
)


router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


def db_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    finally:
        session.close()


def require_login(request: Request) -> None:
    if not request.session.get("user"):
        raise HTTPException(status_code=303, headers={"Location": "/login"})


def render(request: Request, name: str, context: dict | None = None) -> HTMLResponse:
    ctx = {"request": request, "csrf_token": request.session.get("csrf_token", "")}
    ctx.update(context or {})
    return templates.TemplateResponse(request=request, name=name, context=ctx)


@router.get("/login")
def login_page(request: Request):
    request.session.setdefault("csrf_token", new_csrf_token())
    return render(request, "login.html")


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), csrf_token: str = Form(...)):
    ensure_csrf(request, csrf_token)
    settings = get_settings()
    if username == settings.admin_username and verify_password(password, settings.admin_password_hash):
        request.session["user"] = username
        request.session["csrf_token"] = new_csrf_token()
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", {"error": "Invalid username or password"})


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    ensure_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/")
def dashboard(request: Request, session: Session = Depends(db_session)):
    require_login(request)
    cutoff = datetime.utcnow() - timedelta(days=get_settings().telegram_archive_days)
    priority_rows = session.query(CaseMatch.priority, CaseMatch.review_status, func.count(CaseMatch.id)).group_by(CaseMatch.priority, CaseMatch.review_status).all()
    latest_export = session.query(Export).order_by(Export.created_at.desc()).first()
    return render(
        request,
        "dashboard.html",
        {
            "jobs": session.query(Job).count(),
            "cases": session.query(Case).count(),
            "messages": session.query(Message).count(),
            "messages_recent": session.query(Message).filter(Message.posted_at >= cutoff).count(),
            "oldest_message": session.query(func.min(Message.posted_at)).scalar(),
            "newest_message": session.query(func.max(Message.posted_at)).scalar(),
            "exports": session.query(Export).count(),
            "match_stats": priority_rows,
            "pending_review": session.query(CaseMatch).filter(CaseMatch.review_status == "pending", CaseMatch.message_id.isnot(None)).count(),
            "latest_export": latest_export,
        },
    )


@router.get("/upload")
def upload_page(request: Request):
    require_login(request)
    return render(request, "upload.html")


@router.post("/upload")
async def upload_docx(
    request: Request,
    file: UploadFile = File(...),
    csrf_token: str = Form(...),
    document_date: str = Form(default=""),
    period_start: str = Form(default=""),
    period_end: str = Form(default=""),
    night_mode: str | None = Form(default=None),
    rollover_hour: int = Form(default=12),
    session: Session = Depends(db_session),
):
    require_login(request)
    ensure_csrf(request, csrf_token)
    settings = get_settings()
    data = await validate_docx_upload(file, settings.upload_max_mb)
    filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{sanitize_filename(file.filename or 'upload.docx')}"
    path = Path("data/inbox") / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    params = _upload_params(document_date, period_start, period_end, night_mode, rollover_hour)
    job = create_job(session, "process-docx", str(path), params=params)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.get("/jobs")
def jobs(request: Request, session: Session = Depends(db_session)):
    require_login(request)
    return render(request, "jobs.html", {"jobs": session.query(Job).order_by(Job.created_at.desc()).all()})


@router.get("/jobs/{job_id}")
def job_detail(request: Request, job_id: int, session: Session = Depends(db_session)):
    require_login(request)
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    return render(request, "jobs.html", {"jobs": [job], "single": True})


@router.get("/channels")
def channels(request: Request, session: Session = Depends(db_session)):
    require_login(request)
    return render(request, "channels.html", {"channels": session.query(Channel).order_by(Channel.username).all()})


@router.get("/channel-candidates")
def channel_candidates(request: Request, session: Session = Depends(db_session)):
    require_login(request)
    return render(
        request,
        "channel_candidates.html",
        {"candidates": session.query(ChannelCandidate).order_by(ChannelCandidate.updated_at.desc()).all()},
    )


@router.post("/channel-candidates/{candidate_id}/approve")
def approve_candidate(request: Request, candidate_id: int, csrf_token: str = Form(...), session: Session = Depends(db_session)):
    require_login(request)
    ensure_csrf(request, csrf_token)
    candidate = session.get(ChannelCandidate, candidate_id)
    if candidate:
        candidate.status = "approved"
        if candidate.username and not session.query(Channel).filter(Channel.username == candidate.username).one_or_none():
            session.add(Channel(username=candidate.username, title=candidate.title, url=candidate.url, status="active"))
    return RedirectResponse("/channel-candidates", status_code=303)


@router.post("/channel-candidates/{candidate_id}/reject")
def reject_candidate(request: Request, candidate_id: int, csrf_token: str = Form(...), session: Session = Depends(db_session)):
    require_login(request)
    ensure_csrf(request, csrf_token)
    candidate = session.get(ChannelCandidate, candidate_id)
    if candidate:
        candidate.status = "rejected"
    return RedirectResponse("/channel-candidates", status_code=303)


@router.get("/messages")
def messages(request: Request, session: Session = Depends(db_session)):
    require_login(request)
    return render(request, "messages.html", {"messages": session.query(Message).order_by(Message.posted_at.desc()).limit(200).all()})


@router.get("/review")
def review(request: Request, session: Session = Depends(db_session)):
    require_login(request)
    rows = (
        session.query(CaseMatch, Case, Message, Channel)
        .join(Case, Case.id == CaseMatch.case_id)
        .join(Message, Message.id == CaseMatch.message_id)
        .join(Channel, Channel.id == Message.channel_id)
        .filter(CaseMatch.match_type == "telegram")
        .order_by(Case.place_name, Case.id, CaseMatch.priority, CaseMatch.total_score.desc())
        .all()
    )
    return render(request, "review.html", {"rows": rows})


def _set_review_status(match_id: int, status: str, session: Session) -> None:
    match = session.get(CaseMatch, match_id)
    if not match:
        raise HTTPException(404)
    match.review_status = status


@router.post("/review/matches/{match_id}/approve")
def review_approve(request: Request, match_id: int, csrf_token: str = Form(...), session: Session = Depends(db_session)):
    require_login(request)
    ensure_csrf(request, csrf_token)
    _set_review_status(match_id, "approved", session)
    return RedirectResponse("/review", status_code=303)


@router.post("/review/matches/{match_id}/reject")
def review_reject(request: Request, match_id: int, csrf_token: str = Form(...), session: Session = Depends(db_session)):
    require_login(request)
    ensure_csrf(request, csrf_token)
    _set_review_status(match_id, "rejected", session)
    return RedirectResponse("/review", status_code=303)


@router.post("/review/matches/{match_id}/pending")
def review_pending(request: Request, match_id: int, csrf_token: str = Form(...), session: Session = Depends(db_session)):
    require_login(request)
    ensure_csrf(request, csrf_token)
    _set_review_status(match_id, "pending", session)
    return RedirectResponse("/review", status_code=303)


@router.get("/cases")
def cases(request: Request, session: Session = Depends(db_session)):
    require_login(request)
    return render(request, "cases.html", {"cases": session.query(Case).order_by(Case.id.desc()).all()})


@router.get("/cases/{case_id}")
def case_detail(request: Request, case_id: int, session: Session = Depends(db_session)):
    require_login(request)
    case = session.get(Case, case_id)
    if not case:
        raise HTTPException(404)
    return render(request, "case_detail.html", {"case": case})


@router.get("/exports")
def exports(request: Request, session: Session = Depends(db_session)):
    require_login(request)
    return render(request, "exports.html", {"exports": session.query(Export).order_by(Export.created_at.desc()).all()})


def _export_path(export: Export, file: str) -> tuple[str | None, str]:
    if file == "technical":
        if export.docx_path:
            return str(Path(export.docx_path).parent / "technical_report.docx"), "technical_report.docx"
        return None, "technical_report.docx"
    if file == "docx":
        return export.docx_path, "report.docx"
    if file == "html":
        return export.html_path, "report.html"
    return export.zip_path, "evidence.zip"


@router.get("/exports/{export_id}/download")
def web_export_download(request: Request, export_id: int, file: str = "zip", session: Session = Depends(db_session)):
    require_login(request)
    export = session.get(Export, export_id)
    path, filename = _export_path(export, file) if export else (None, "")
    if not export or not path or not Path(path).exists():
        raise HTTPException(404)
    return FileResponse(path, filename=filename)


@router.post("/channels/collect-once")
def queue_collect_once(request: Request, csrf_token: str = Form(...), session: Session = Depends(db_session)):
    require_login(request)
    ensure_csrf(request, csrf_token)
    create_job(session, "collect-once")
    return RedirectResponse("/jobs", status_code=303)


@router.post("/cases/import-latest")
def import_latest(request: Request, csrf_token: str = Form(...), session: Session = Depends(db_session)):
    require_login(request)
    ensure_csrf(request, csrf_token)
    latest = sorted(Path("data/inbox").glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if latest:
        create_job(session, "process-docx", str(latest[0]))
    return RedirectResponse("/jobs", status_code=303)


@router.post("/cases/match")
def queue_match(request: Request, csrf_token: str = Form(...), session: Session = Depends(db_session)):
    require_login(request)
    ensure_csrf(request, csrf_token)
    create_job(session, "match-cases")
    return RedirectResponse("/jobs", status_code=303)


@router.post("/exports/build-latest")
def queue_export(request: Request, csrf_token: str = Form(...), session: Session = Depends(db_session)):
    require_login(request)
    ensure_csrf(request, csrf_token)
    create_job(session, "export-report")
    return RedirectResponse("/jobs", status_code=303)


@router.post("/api/documents/upload", dependencies=[Depends(require_api_auth)])
async def api_upload(
    file: UploadFile = File(...),
    document_date: str = Form(default=""),
    period_start: str = Form(default=""),
    period_end: str = Form(default=""),
    night_mode: str | None = Form(default=None),
    rollover_hour: int = Form(default=12),
    session: Session = Depends(db_session),
):
    settings = get_settings()
    data = await validate_docx_upload(file, settings.upload_max_mb)
    filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{sanitize_filename(file.filename or 'upload.docx')}"
    path = Path("data/inbox") / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    params = _upload_params(document_date, period_start, period_end, night_mode, rollover_hour)
    job = create_job(session, "process-docx", str(path), params=params)
    return {"ok": True, "job_id": job.id, "filename": filename}


def _upload_params(
    document_date: str,
    period_start: str,
    period_end: str,
    night_mode: str | None,
    rollover_hour: int,
) -> dict | None:
    params: dict = {}
    if period_start:
        params["period_start"] = period_start
        if period_end:
            params["period_end"] = period_end
        if night_mode:
            params["night_mode"] = True
        params["rollover_hour"] = rollover_hour
    elif document_date:
        params["document_date"] = document_date
    return params or None


@router.get("/api/jobs/{job_id}", dependencies=[Depends(require_api_auth)])
def api_job(job_id: int, session: Session = Depends(db_session)):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "current_step": job.current_step,
        "params": job.params_json,
        "error": job.error,
        "output_path": job.output_path,
    }


@router.get("/api/exports/latest", dependencies=[Depends(require_api_auth)])
def api_latest_export(session: Session = Depends(db_session)):
    export = session.query(Export).filter(Export.zip_path.isnot(None)).order_by(Export.created_at.desc()).first()
    if not export or not export.zip_path or not Path(export.zip_path).exists():
        raise HTTPException(404)
    return FileResponse(export.zip_path, filename="evidence.zip")


@router.get("/api/exports/{export_id}/download", dependencies=[Depends(require_api_auth)])
def api_export_download(export_id: int, session: Session = Depends(db_session)):
    export = session.get(Export, export_id)
    if not export or not export.zip_path or not Path(export.zip_path).exists():
        raise HTTPException(404)
    return FileResponse(export.zip_path, filename=f"evidence-{export.id}.zip")
