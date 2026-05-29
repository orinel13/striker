from __future__ import annotations

import argparse
import asyncio
import getpass
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

import uvicorn

from app.config import ConfigError, ensure_data_dirs, get_settings, require_api_token, require_web_secrets
from app.db import SessionLocal, init_db, session_scope
from app.documents.docx_importer import import_docx
from app.documents.report_exporter import export_report
from app.firms.client import fetch_firms_for_all_cases
from app.geo.places_loader import load_places_csv
from app.jobs import create_job, worker_loop
from app.logging_setup import setup_logging
from app.matching.case_matcher import match_cases
from app.matching.evidence import render_evidence
from app.models import Channel, ChannelCandidate, Export, Job
from app.security import hash_password
from app.telegram.client import TelegramClientFactory
from app.telegram.collector import collect_loop, collect_once


def cmd_init_db(_args) -> None:
    ensure_data_dirs()
    init_db()
    print("Database initialized.")


def cmd_load_places(args) -> None:
    init_db()
    with session_scope() as session:
        count = load_places_csv(session, args.path)
    print(f"Loaded {count} places.")


def cmd_make_password_hash(_args) -> None:
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Repeat password: ")
    if password != confirm:
        raise ConfigError("Passwords do not match")
    print(hash_password(password))


def cmd_telegram_login(_args) -> None:
    async def _login():
        async with TelegramClientFactory().create() as client:
            me = await client.get_me()
            print(f"Telegram session ready: {getattr(me, 'username', None) or getattr(me, 'id', '')}")

    asyncio.run(_login())


def cmd_collect_once(_args) -> None:
    init_db()
    print(asyncio.run(collect_once()))


def cmd_collect_loop(_args) -> None:
    init_db()
    asyncio.run(collect_loop())


def cmd_worker_loop(_args) -> None:
    init_db()
    worker_loop(SessionLocal)


def cmd_import_docx(args) -> None:
    init_db()
    with session_scope() as session:
        cases = import_docx(session, args.path)
    print(f"Imported {len(cases)} cases.")


def cmd_fetch_firms(_args) -> None:
    init_db()
    with session_scope() as session:
        count = fetch_firms_for_all_cases(session)
    print(f"Saved {count} FIRMS points.")


def cmd_match_cases(_args) -> None:
    init_db()
    with session_scope() as session:
        count = match_cases(session)
    print(f"Created {count} matches.")


def cmd_render_evidence(_args) -> None:
    init_db()
    with session_scope() as session:
        count = render_evidence(session)
    print(f"Rendered {count} evidence files.")


def cmd_export_report(_args) -> None:
    init_db()
    with session_scope() as session:
        export = export_report(session)
        print(export.zip_path)


def cmd_run_web(_args) -> None:
    settings = get_settings()
    require_web_secrets(settings)
    require_api_token(settings)
    uvicorn.run("app.web.main:app", host=settings.web_host, port=settings.web_port, reload=settings.app_env != "production")


def cmd_approve_channel(args) -> None:
    init_db()
    username = args.username.lower().lstrip("@")
    with session_scope() as session:
        candidate = session.query(ChannelCandidate).filter(ChannelCandidate.username == username).one_or_none()
        if candidate:
            candidate.status = "approved"
        if not session.query(Channel).filter(Channel.username == username).one_or_none():
            session.add(Channel(username=username, url=f"https://t.me/{username}", status="active"))
    print(f"Approved {username}.")


def cmd_reject_channel(args) -> None:
    init_db()
    username = args.username.lower().lstrip("@")
    with session_scope() as session:
        candidate = session.query(ChannelCandidate).filter(ChannelCandidate.username == username).one_or_none()
        if candidate:
            candidate.status = "rejected"
    print(f"Rejected {username}.")


def cmd_create_job_from_docx(args) -> None:
    init_db()
    with session_scope() as session:
        job = create_job(session, "process-docx", args.path)
        print(job.id)


def cmd_cleanup_exports(_args) -> None:
    settings = get_settings()
    cutoff = datetime.utcnow() - timedelta(days=settings.export_retention_days)
    init_db()
    removed = 0
    with session_scope() as session:
        exports = session.query(Export).filter(Export.created_at < cutoff).all()
        for export in exports:
            for path in [export.docx_path, export.html_path, export.zip_path]:
                if path and Path(path).exists():
                    root = Path(path).parent
                    if root.name and root.parent == Path("data/exports"):
                        shutil.rmtree(root, ignore_errors=True)
                        break
            session.delete(export)
            removed += 1
    print(f"Removed {removed} old exports.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    commands = {
        "init-db": (cmd_init_db, []),
        "make-password-hash": (cmd_make_password_hash, []),
        "telegram-login": (cmd_telegram_login, []),
        "collect-once": (cmd_collect_once, []),
        "collect-loop": (cmd_collect_loop, []),
        "worker-loop": (cmd_worker_loop, []),
        "fetch-firms": (cmd_fetch_firms, []),
        "match-cases": (cmd_match_cases, []),
        "render-evidence": (cmd_render_evidence, []),
        "export-report": (cmd_export_report, []),
        "run-web": (cmd_run_web, []),
        "cleanup-exports": (cmd_cleanup_exports, []),
    }
    for name, (func, _opts) in commands.items():
        p = sub.add_parser(name)
        p.set_defaults(func=func)
    p = sub.add_parser("load-places")
    p.add_argument("path", nargs="?", default="data/places_extra.csv")
    p.set_defaults(func=cmd_load_places)
    p = sub.add_parser("import-docx")
    p.add_argument("path")
    p.set_defaults(func=cmd_import_docx)
    p = sub.add_parser("approve-channel")
    p.add_argument("username")
    p.set_defaults(func=cmd_approve_channel)
    p = sub.add_parser("reject-channel")
    p.add_argument("username")
    p.set_defaults(func=cmd_reject_channel)
    p = sub.add_parser("create-job-from-docx")
    p.add_argument("path")
    p.set_defaults(func=cmd_create_job_from_docx)
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    ensure_data_dirs()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
