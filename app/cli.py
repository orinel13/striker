from __future__ import annotations

import argparse
import asyncio
import getpass
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import uvicorn
from sqlalchemy import func

from app.batches import activate_batch, archive_batch, cleanup_batches, create_batch, current_batch_id, delete_batch, get_current_batch, update_batch_counts
from app.config import ConfigError, ensure_data_dirs, get_settings, require_api_token, require_web_secrets
from app.db import SessionLocal, init_db, session_scope
from app.documents.docx_importer import import_docx
from app.documents.report_exporter import export_report
from app.documents.strike_table_parser import parse_docx_strike_rows
from app.firms.client import fetch_firms_for_all_cases
from app.geo.places_loader import load_places_csv
from app.jobs import create_job, worker_loop
from app.logging_setup import setup_logging
from app.matching.case_matcher import candidates_for_case, evidence_window, legacy_match_cases, localize_message_time, match_cases, score_message_for_case
from app.matching.evidence import render_evidence
from app.models import Case, CaseBatch, CaseMatch, Channel, ChannelCandidate, Export, Job, Message
from app.security import hash_password
from app.telegram.channel_discovery import approve_channel_candidate, dedupe_channel_candidates, normalize_channel_username, set_channel_candidate_status
from app.telegram.client import TelegramClientFactory
from app.telegram.collector import collect_latest_once, collect_loop, collect_once, prune_archive, reindex_message_places
from app.telegram.normalizer import normalize_text


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


def cmd_collect_latest_once(_args) -> None:
    init_db()
    print(asyncio.run(collect_latest_once()))


def cmd_collect_loop(_args) -> None:
    init_db()
    asyncio.run(collect_loop())


def cmd_worker_loop(_args) -> None:
    init_db()
    worker_loop(SessionLocal)


def cmd_import_docx(args) -> None:
    init_db()
    document_date, period_start, period_end = _date_args(args)
    with session_scope() as session:
        batch_id = args.batch_id
        if not batch_id:
            batch = create_batch(
                session,
                source_filename=Path(args.path).name,
                original_path=args.path,
                title=args.batch_title,
                document_date=document_date,
                period_start=period_start,
                period_end=period_end,
                night_mode=args.night_mode,
                rollover_hour=args.rollover_hour,
                activate=args.activate,
                archive_previous=args.archive_previous,
            )
            batch_id = batch.id
        cases = import_docx(
            session,
            args.path,
            document_date=document_date,
            default_year=args.default_year,
            period_start=period_start,
            period_end=period_end,
            night_mode=args.night_mode,
            rollover_hour=args.rollover_hour,
            batch_id=batch_id,
        )
        update_batch_counts(session, batch_id)
    print(f"Imported {len(cases)} cases. batch_id={batch_id}")


def cmd_inspect_docx(args) -> None:
    document_date, period_start, period_end = _date_args(args)
    rows = parse_docx_strike_rows(
        args.path,
        document_date=document_date,
        default_year=args.default_year,
        period_start=period_start,
        period_end=period_end,
        night_mode=args.night_mode,
        rollover_hour=args.rollover_hour,
    )
    print("row_index | date | time/window | oblast | place | lat | lon | warnings")
    for row in rows:
        if row.time_window_start and row.time_window_end:
            window = f"{row.time_window_start.isoformat()}..{row.time_window_end.isoformat()}"
        else:
            window = row.event_time_local or (
                f"{row.time_range_start or ''}-{row.time_range_end or ''}" if row.time_range_start or row.time_range_end else ""
            )
        print(
            " | ".join(
                [
                    str(row.row_index),
                    row.event_date.isoformat() if row.event_date else "",
                    window,
                    row.oblast or "",
                    row.place_name_raw or row.reference_text or "",
                    f"{row.lat:.5f}" if row.lat is not None else "",
                    f"{row.lon:.5f}" if row.lon is not None else "",
                    "; ".join(row.parser_warnings),
                ]
            )
        )


def cmd_fetch_firms(_args) -> None:
    init_db()
    with session_scope() as session:
        count = fetch_firms_for_all_cases(session)
    print(f"Saved {count} FIRMS points.")


def cmd_match_cases(_args) -> None:
    init_db()
    with session_scope() as session:
        batch_id = getattr(_args, "batch_id", None)
        stats = (
            legacy_match_cases(session, batch_id=batch_id, all_batches=getattr(_args, "all_batches", False))
            if getattr(_args, "legacy", False)
            else match_cases(session, batch_id=batch_id, all_batches=getattr(_args, "all_batches", False))
        )
    if isinstance(stats, dict):
        print(f"Matched {stats['matches']} telegram matches, pending={stats['pending']}")


def cmd_archive_stats(_args) -> None:
    init_db()
    settings = get_settings()
    cutoff = datetime.utcnow() - timedelta(days=settings.telegram_archive_days)
    with session_scope() as session:
        total, min_posted, max_posted = session.query(func.count(Message.id), func.min(Message.posted_at), func.max(Message.posted_at)).one()
        recent = session.query(func.count(Message.id)).filter(Message.posted_at >= cutoff).scalar()
        old = session.query(func.count(Message.id)).filter(Message.posted_at < cutoff).scalar()
        print(f"total messages: {total}")
        print(f"recent messages ({settings.telegram_archive_days}d): {recent}")
        print(f"old messages: {old}")
        print(f"min posted_at: {min_posted}")
        print(f"max posted_at: {max_posted}")
        print("username | count | min(posted_at) | max(posted_at) | last_message_id | max(tg_message_id)")
        rows = (
            session.query(
                Channel.username,
                func.count(Message.id),
                func.min(Message.posted_at),
                func.max(Message.posted_at),
                Channel.last_message_id,
                func.max(Message.tg_message_id),
            )
            .outerjoin(Message, Message.channel_id == Channel.id)
            .group_by(Channel.id)
            .order_by(Channel.username)
            .all()
        )
        for row in rows:
            print(" | ".join("" if value is None else str(value) for value in row))


def cmd_reset_channel_cursors(args) -> None:
    init_db()
    if not args.all and not args.username:
        raise ConfigError("Use --all or --username")
    with session_scope() as session:
        query = session.query(Channel)
        if args.username:
            query = query.filter(Channel.username == args.username.lstrip("@").lower())
        count = 0
        for channel in query.all():
            channel.last_message_id = 0
            channel.last_collected_at = None
            count += 1
    print(f"Reset cursors: {count}")


def cmd_reindex_message_places(_args) -> None:
    init_db()
    with session_scope() as session:
        count = reindex_message_places(session, days=_args.days, all_messages=_args.all, batch_size=_args.batch_size, progress=True)
    print(f"Reindexed messages: {count}")


def cmd_prune_archive(args) -> None:
    init_db()
    with session_scope() as session:
        count = prune_archive(session, args.days, vacuum=args.vacuum)
    print(f"Pruned messages: {count}")


def cmd_debug_match_case(args) -> None:
    init_db()
    with session_scope() as session:
        case = session.get(Case, args.case_id)
        if not case:
            raise ConfigError(f"Case not found: {args.case_id}")
        start_utc, end_utc = evidence_window(case)
        print(f"case id={case.id} place={case.place_name} date={case.event_date} window_local={case.time_window_start}..{case.time_window_end}")
        print(f"evidence_window_utc={start_utc}..{end_utc}")
        messages, _, _ = candidates_for_case(session, case, limit=args.limit)
        for message in messages:
            channel = session.get(Channel, message.channel_id)
            scored = score_message_for_case(session, case, message)
            reasons = ",".join(scored["reasons"]) or "accepted_candidate"
            snippet = (message.text or "").replace("\n", " ")[:160]
            print(
                f"message_id={message.id} channel={channel.username if channel else ''}/{channel.title if channel else ''} "
                f"posted_utc={message.posted_at} posted_local={scored['posted_at_local']} url={message.url or ''} "
                f"time={scored['time_score']} geo={scored['geo_score']} keyword={scored['keyword_score']} "
                f"source={scored['source_score']} total={scored['total']} would_priority={scored['priority']} "
                f"reasons={reasons} text={snippet}"
            )


def cmd_search_by_case(args) -> None:
    init_db()
    with session_scope() as session:
        case = session.get(Case, args.case_id)
        if not case:
            raise ConfigError(f"Case not found: {args.case_id}")
        messages, start_utc, end_utc = candidates_for_case(session, case, limit=args.limit)
        print(f"case id={case.id} place={case.place_name} evidence_window_utc={start_utc}..{end_utc}")
        for message in messages:
            channel = session.get(Channel, message.channel_id)
            snippet = (message.text or "").replace("\n", " ")[:220]
            print(f"{message.posted_at} | {localize_message_time(message.posted_at)} | {channel.username if channel else ''} | {message.url or ''} | {snippet}")


def cmd_search_archive(args) -> None:
    init_db()
    query = normalize_text(" ".join(args.query))
    with session_scope() as session:
        messages = session.query(Message).filter(Message.normalized_text.contains(query))
        if args.date:
            day = date.fromisoformat(args.date)
            start = datetime.combine(day, datetime.min.time())
            end = datetime.combine(day, datetime.max.time())
            messages = messages.filter(Message.posted_at >= start, Message.posted_at <= end)
        for message in messages.order_by(Message.posted_at.desc()).limit(args.limit).all():
            channel = session.get(Channel, message.channel_id)
            snippet = (message.text or "").replace("\n", " ")[:220]
            print(f"{message.posted_at} | {channel.username if channel else message.channel_id} | {message.url or ''} | {snippet}")


def cmd_render_evidence(_args) -> None:
    init_db()
    with session_scope() as session:
        count = render_evidence(session, batch_id=getattr(_args, "batch_id", None) or current_batch_id(session), include_pending=getattr(_args, "include_pending", False))
    print(f"Rendered {count} evidence files.")


def cmd_export_report(_args) -> None:
    init_db()
    with session_scope() as session:
        batch_id = current_batch_id(session, _args.batch_id)
        export = export_report(
            session,
            style=_args.style,
            include_technical_appendix=_args.include_technical_appendix,
            include_pending=_args.include_pending,
            batch_id=batch_id,
            text_only=_args.text_only and not (_args.with_local_cards or _args.external_screenshots),
            with_local_cards=_args.with_local_cards,
            external_screenshots=_args.external_screenshots,
            include_case_refs=_args.include_case_refs,
            include_unmatched_appendix=_args.include_unmatched_appendix,
        )
        print(export.zip_path)


def cmd_list_batches(_args) -> None:
    init_db()
    with session_scope() as session:
        current = get_current_batch(session)
        print("id | current | status | source | created_at | cases | matches | pending | approved")
        for batch in session.query(CaseBatch).order_by(CaseBatch.created_at.desc(), CaseBatch.id.desc()).all():
            update_batch_counts(session, batch.id)
            print(
                " | ".join(
                    [
                        str(batch.id),
                        "*" if current and current.id == batch.id else "",
                        batch.status,
                        batch.source_filename or batch.title or "",
                        str(batch.created_at),
                        str(batch.cases_count),
                        str(batch.matches_count),
                        str(batch.pending_count),
                        str(batch.approved_count),
                    ]
                )
            )


def cmd_show_batch(args) -> None:
    init_db()
    with session_scope() as session:
        batch = session.get(CaseBatch, args.batch_id)
        if not batch:
            raise ConfigError(f"Batch not found: {args.batch_id}")
        update_batch_counts(session, batch.id)
        print(f"id={batch.id}")
        print(f"status={batch.status}")
        print(f"title={batch.title}")
        print(f"source={batch.source_filename}")
        print(f"original_path={batch.original_path}")
        print(f"created_at={batch.created_at}")
        print(f"period={batch.document_date or batch.period_start}..{batch.period_end}")
        print(f"cases={batch.cases_count} matches={batch.matches_count} pending={batch.pending_count} approved={batch.approved_count}")


def cmd_activate_batch(args) -> None:
    init_db()
    with session_scope() as session:
        batch = activate_batch(session, args.batch_id, archive_previous=args.archive_previous)
    print(f"Activated batch {batch.id}.")


def cmd_archive_batch(args) -> None:
    init_db()
    with session_scope() as session:
        batch = archive_batch(session, args.batch_id)
    print(f"Archived batch {batch.id}.")


def cmd_delete_batch(args) -> None:
    if not args.yes:
        raise ConfigError("Use --yes to delete a batch. Telegram archive will not be touched.")
    init_db()
    with session_scope() as session:
        delete_batch(session, args.batch_id)
    print(f"Deleted batch {args.batch_id}. Telegram archive was kept.")


def cmd_cleanup_batches(args) -> None:
    if args.delete_archived and not args.yes:
        raise ConfigError("Use --yes with --delete-archived")
    init_db()
    with session_scope() as session:
        changed = cleanup_batches(session, archive_older_than_days=args.archive_older_than_days, delete_archived=args.delete_archived)
    print(f"Changed batches: {changed}. Telegram archive was kept.")


def cmd_clear_current_batch(args) -> None:
    if not args.yes:
        raise ConfigError("Use --yes to clear current batch. Telegram archive will not be touched.")
    init_db()
    with session_scope() as session:
        batch = get_current_batch(session)
        if not batch:
            print("No current batch.")
            return
        batch_id = batch.id
        delete_batch(session, batch_id)
    print(f"Deleted current batch {batch_id}. Telegram archive was kept.")


def cmd_clear_all_batches(args) -> None:
    if not args.yes or not args.keep_telegram:
        raise ConfigError("Use --yes --keep-telegram. Telegram archive will not be touched.")
    init_db()
    with session_scope() as session:
        ids = [row[0] for row in session.query(CaseBatch.id).all()]
        for batch_id in ids:
            delete_batch(session, batch_id)
    print(f"Deleted {len(ids)} batches. Telegram archive was kept.")


def cmd_run_web(_args) -> None:
    settings = get_settings()
    require_web_secrets(settings)
    require_api_token(settings)
    uvicorn.run("app.web.main:app", host=settings.web_host, port=settings.web_port, reload=settings.app_env != "production")


def cmd_approve_channel(args) -> None:
    init_db()
    username = normalize_channel_username(args.username)
    with session_scope() as session:
        approve_channel_candidate(session, username)
    print(f"Approved {username}.")


def cmd_reject_channel(args) -> None:
    init_db()
    username = normalize_channel_username(args.username)
    with session_scope() as session:
        set_channel_candidate_status(session, username, "rejected")
    print(f"Rejected {username}.")


def cmd_list_channel_candidates(args) -> None:
    init_db()
    with session_scope() as session:
        query = session.query(ChannelCandidate)
        if args.status != "all":
            query = query.filter(ChannelCandidate.status == args.status)
        for c in query.order_by(ChannelCandidate.thematic_score.desc(), ChannelCandidate.updated_at.desc()).limit(args.limit).all():
            print(f"{c.username} | {c.status} | mentions={c.mentions_count} | score={c.thematic_score} | {c.title or ''}")


def cmd_approve_channel_candidate(args) -> None:
    init_db()
    username = normalize_channel_username(args.username)
    with session_scope() as session:
        approve_channel_candidate(session, username)
    print(f"Approved candidate {username}.")


def cmd_reject_channel_candidate(args) -> None:
    init_db()
    username = normalize_channel_username(args.username)
    with session_scope() as session:
        set_channel_candidate_status(session, username, "rejected")
    print(f"Rejected candidate {username}.")


def cmd_archive_channel_candidate(args) -> None:
    init_db()
    username = normalize_channel_username(args.username)
    with session_scope() as session:
        set_channel_candidate_status(session, username, "archived")
    print(f"Archived candidate {username}.")


def cmd_cleanup_channel_candidates(args) -> None:
    if not args.yes:
        raise ConfigError("Use --yes")
    init_db()
    cutoff = datetime.utcnow() - timedelta(days=args.older_than_days)
    with session_scope() as session:
        deleted = session.query(ChannelCandidate).filter(ChannelCandidate.status == args.status, ChannelCandidate.updated_at < cutoff).delete(synchronize_session=False)
    print(f"Deleted candidates: {deleted}")


def cmd_dedupe_channel_candidates(_args) -> None:
    init_db()
    with session_scope() as session:
        removed = dedupe_channel_candidates(session)
    print(f"Channel candidates deduplicated. removed={removed}")


def cmd_create_job_from_docx(args) -> None:
    init_db()
    params = _job_params_from_args(args)
    with session_scope() as session:
        batch = create_batch(
            session,
            source_filename=Path(args.path).name,
            original_path=args.path,
            title=getattr(args, "batch_title", None),
            document_date=date.fromisoformat(params["document_date"]) if params.get("document_date") else None,
            period_start=date.fromisoformat(params["period_start"]) if params.get("period_start") else None,
            period_end=date.fromisoformat(params["period_end"]) if params.get("period_end") else None,
            night_mode=bool(params.get("night_mode")),
            rollover_hour=int(params.get("rollover_hour", 12)),
            activate=getattr(args, "activate", True),
            archive_previous=getattr(args, "archive_previous", False),
        )
        job = create_job(session, "process-docx", args.path, params=params or None, batch_id=batch.id)
        print(f"job_id={job.id} batch_id={batch.id}")


def _date_args(args) -> tuple[date | None, date | None, date | None]:
    document_date = date.fromisoformat(args.document_date) if getattr(args, "document_date", None) else None
    period_start = date.fromisoformat(args.period_start) if getattr(args, "period_start", None) else None
    period_end = date.fromisoformat(args.period_end) if getattr(args, "period_end", None) else None
    if period_start:
        document_date = None
    return document_date, period_start, period_end


def _job_params_from_args(args) -> dict:
    params = {}
    for name in ["document_date", "period_start", "period_end"]:
        value = getattr(args, name, None)
        if value:
            params[name] = value
    if getattr(args, "default_year", None):
        params["default_year"] = args.default_year
    if getattr(args, "night_mode", False):
        params["night_mode"] = True
    if getattr(args, "rollover_hour", None) != 12:
        params["rollover_hour"] = args.rollover_hour
    return params


def _add_docx_date_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--document-date", help="Document/event date in YYYY-MM-DD format")
    parser.add_argument("--default-year", type=int, help="Year for short dates like 20.05")
    parser.add_argument("--period-start", help="Period start date in YYYY-MM-DD format")
    parser.add_argument("--period-end", help="Period end date in YYYY-MM-DD format")
    parser.add_argument("--night-mode", action="store_true", help="Treat 00:00-11:59 as the period end date")
    parser.add_argument("--rollover-hour", type=int, default=12, help="Night-mode rollover hour, default 12")


def _add_batch_import_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--batch-title")
    parser.add_argument("--batch-id", type=int)
    parser.add_argument("--activate", dest="activate", action="store_true", default=True)
    parser.add_argument("--no-activate", dest="activate", action="store_false")
    parser.add_argument("--archive-previous", action="store_true")


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
        "collect-latest-once": (cmd_collect_latest_once, []),
        "collect-loop": (cmd_collect_loop, []),
        "worker-loop": (cmd_worker_loop, []),
        "fetch-firms": (cmd_fetch_firms, []),
        "archive-stats": (cmd_archive_stats, []),
        "run-web": (cmd_run_web, []),
        "cleanup-exports": (cmd_cleanup_exports, []),
        "list-batches": (cmd_list_batches, []),
        "dedupe-channel-candidates": (cmd_dedupe_channel_candidates, []),
    }
    for name, (func, _opts) in commands.items():
        p = sub.add_parser(name)
        p.set_defaults(func=func)
    p = sub.add_parser("match-cases")
    p.add_argument("--legacy", action="store_true", help="Compatibility flag; fast matcher is used by default")
    p.add_argument("--batch-id", type=int)
    p.add_argument("--all-batches", action="store_true")
    p.set_defaults(func=cmd_match_cases)
    p = sub.add_parser("reindex-message-places")
    p.add_argument("--days", type=int, default=get_settings().telegram_archive_days)
    p.add_argument("--all", action="store_true")
    p.add_argument("--batch-size", type=int, default=500)
    p.set_defaults(func=cmd_reindex_message_places)
    p = sub.add_parser("export-report")
    p.add_argument("--style", choices=["osint", "technical"], default="osint")
    p.add_argument("--include-technical-appendix", action="store_true")
    p.add_argument("--include-pending", action="store_true")
    p.add_argument("--batch-id", type=int)
    p.add_argument("--text-only", action="store_true", default=True)
    p.add_argument("--with-local-cards", action="store_true")
    p.add_argument("--external-screenshots", action="store_true")
    p.add_argument("--include-case-refs", action="store_true")
    p.add_argument("--include-unmatched-appendix", action="store_true")
    p.set_defaults(func=cmd_export_report)
    p = sub.add_parser("render-evidence")
    p.add_argument("--batch-id", type=int)
    p.add_argument("--approved-only", action="store_true", default=True)
    p.add_argument("--include-pending", action="store_true")
    p.set_defaults(func=cmd_render_evidence)
    p = sub.add_parser("show-batch")
    p.add_argument("batch_id", type=int)
    p.set_defaults(func=cmd_show_batch)
    p = sub.add_parser("activate-batch")
    p.add_argument("batch_id", type=int)
    p.add_argument("--archive-previous", action="store_true")
    p.set_defaults(func=cmd_activate_batch)
    p = sub.add_parser("archive-batch")
    p.add_argument("batch_id", type=int)
    p.set_defaults(func=cmd_archive_batch)
    p = sub.add_parser("delete-batch")
    p.add_argument("batch_id", type=int)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_delete_batch)
    p = sub.add_parser("cleanup-batches")
    p.add_argument("--archive-older-than-days", type=int)
    p.add_argument("--delete-archived", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_cleanup_batches)
    p = sub.add_parser("clear-current-batch")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_clear_current_batch)
    p = sub.add_parser("clear-all-batches")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--keep-telegram", action="store_true")
    p.set_defaults(func=cmd_clear_all_batches)
    p = sub.add_parser("reset-channel-cursors")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true")
    group.add_argument("--username")
    p.set_defaults(func=cmd_reset_channel_cursors)
    p = sub.add_parser("debug-match-case")
    p.add_argument("case_id", type=int)
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_debug_match_case)
    p = sub.add_parser("search-by-case")
    p.add_argument("case_id", type=int)
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_search_by_case)
    p = sub.add_parser("search-archive")
    p.add_argument("query", nargs="+")
    p.add_argument("--date")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_search_archive)
    p = sub.add_parser("prune-archive")
    p.add_argument("--days", type=int, default=get_settings().telegram_archive_days)
    p.add_argument("--vacuum", action="store_true")
    p.set_defaults(func=cmd_prune_archive)
    p = sub.add_parser("load-places")
    p.add_argument("path", nargs="?", default="data/places_extra.csv")
    p.set_defaults(func=cmd_load_places)
    p = sub.add_parser("import-docx")
    p.add_argument("path")
    _add_docx_date_args(p)
    _add_batch_import_args(p)
    p.set_defaults(func=cmd_import_docx)
    p = sub.add_parser("inspect-docx")
    p.add_argument("path")
    _add_docx_date_args(p)
    p.set_defaults(func=cmd_inspect_docx)
    p = sub.add_parser("approve-channel")
    p.add_argument("username")
    p.set_defaults(func=cmd_approve_channel)
    p = sub.add_parser("reject-channel")
    p.add_argument("username")
    p.set_defaults(func=cmd_reject_channel)
    p = sub.add_parser("list-channel-candidates")
    p.add_argument("--status", choices=["pending", "approved", "rejected", "archived", "all"], default="pending")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_list_channel_candidates)
    p = sub.add_parser("approve-channel-candidate")
    p.add_argument("username")
    p.set_defaults(func=cmd_approve_channel_candidate)
    p = sub.add_parser("reject-channel-candidate")
    p.add_argument("username")
    p.set_defaults(func=cmd_reject_channel_candidate)
    p = sub.add_parser("archive-channel-candidate")
    p.add_argument("username")
    p.set_defaults(func=cmd_archive_channel_candidate)
    p = sub.add_parser("cleanup-channel-candidates")
    p.add_argument("--status", choices=["rejected", "archived"], required=True)
    p.add_argument("--older-than-days", type=int, required=True)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_cleanup_channel_candidates)
    p = sub.add_parser("create-job-from-docx")
    p.add_argument("path")
    _add_docx_date_args(p)
    _add_batch_import_args(p)
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
