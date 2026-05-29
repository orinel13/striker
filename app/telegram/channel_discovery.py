from __future__ import annotations

import json
import re
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Channel, ChannelCandidate, Message


USERNAME_RE = re.compile(r"(?:https?://t\.me/|t\.me/|@)(?P<username>[A-Za-z][A-Za-z0-9_]{3,31})(?:/\d+)?", re.IGNORECASE)
IGNORED_USERNAMES = {"share", "s", "joinchat", "addstickers"}


def normalize_channel_username(value: str | None) -> str:
    text = (value or "").strip().lower()
    for prefix in ["https://t.me/", "http://t.me/", "t.me/"]:
        if text.startswith(prefix):
            text = text[len(prefix) :]
    text = text.lstrip("@").split("/", 1)[0]
    return re.sub(r"[^a-z0-9_]", "", text)


def _should_ignore_username(username: str, ignore_bots: bool = True) -> bool:
    if not username or len(username) < 4 or username in IGNORED_USERNAMES:
        return True
    if ignore_bots and (username.endswith("bot") or username.endswith("_bot")):
        return True
    return False


def extract_channel_usernames(text: str) -> set[str]:
    usernames: set[str] = set()
    for match in USERNAME_RE.finditer(text or ""):
        username = normalize_channel_username(match.group("username"))
        if username and not _should_ignore_username(username, ignore_bots=get_settings().channel_candidate_ignore_bots):
            usernames.add(username)
    return usernames


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, list) else []
    except json.JSONDecodeError:
        return []


def _append_limited(value: str | None, item, limit: int) -> str:
    rows = _json_list(value)
    if item not in rows:
        rows.append(item)
    return json.dumps(rows[-limit:], ensure_ascii=False)


def _message_sample(session: Session, message: Message) -> dict:
    channel = session.get(Channel, message.channel_id)
    return {
        "posted_at": message.posted_at.isoformat() if message.posted_at else None,
        "source_channel_id": message.channel_id,
        "source_channel": channel.username if channel else None,
        "message_id": message.id,
        "tg_message_id": message.tg_message_id,
        "url": message.url,
        "snippet": (message.text or "").replace("\n", " ")[:500],
    }


def record_candidates(session: Session, message: Message, thematic_score: float) -> int:
    settings = get_settings()
    source_channel = session.get(Channel, message.channel_id)
    source_username = normalize_channel_username(source_channel.username if source_channel else None)
    usernames = extract_channel_usernames(message.text)
    if message.fwd_from_channel:
        forwarded = normalize_channel_username(message.fwd_from_channel)
        if forwarded and not _should_ignore_username(forwarded, settings.channel_candidate_ignore_bots):
            usernames.add(forwarded)
    count = 0
    for username in sorted(usernames):
        if username == source_username or _should_ignore_username(username, settings.channel_candidate_ignore_bots):
            continue
        active_channel = session.query(Channel).filter(Channel.username == username, Channel.status == "active").one_or_none()
        existing = session.query(ChannelCandidate).filter(ChannelCandidate.username == username).one_or_none()
        if active_channel and not existing:
            continue
        if not existing and thematic_score < settings.channel_candidate_min_score:
            continue
        sample = _message_sample(session, message)
        if existing:
            existing.mentions_count = (existing.mentions_count or 0) + 1
            existing.thematic_score = max(existing.thematic_score or 0, thematic_score)
            existing.last_seen_at = message.posted_at or datetime.utcnow()
            existing.last_seen_message_id = message.tg_message_id
            existing.sample_texts_json = _append_limited(existing.sample_texts_json, sample["snippet"], settings.channel_candidate_max_samples)
            existing.source_messages_json = _append_limited(existing.source_messages_json, sample, settings.channel_candidate_max_samples)
            if active_channel and existing.status == "pending":
                existing.status = "approved"
        else:
            session.add(
                ChannelCandidate(
                    username=username,
                    url=f"https://t.me/{username}",
                    source_channel_id=message.channel_id,
                    first_seen_message_id=message.tg_message_id,
                    last_seen_message_id=message.tg_message_id,
                    first_seen_at=message.posted_at or datetime.utcnow(),
                    last_seen_at=message.posted_at or datetime.utcnow(),
                    mentions_count=1,
                    thematic_score=thematic_score,
                    status="pending",
                    sample_texts_json=json.dumps([sample["snippet"]], ensure_ascii=False),
                    source_messages_json=json.dumps([sample], ensure_ascii=False),
                )
            )
        count += 1
    return count


def approve_channel_candidate(session: Session, username: str) -> ChannelCandidate | None:
    normalized = normalize_channel_username(username)
    candidate = session.query(ChannelCandidate).filter(ChannelCandidate.username == normalized).one_or_none()
    if candidate:
        candidate.status = "approved"
    channel = session.query(Channel).filter(Channel.username == normalized).one_or_none()
    if channel:
        channel.status = "active"
        if candidate:
            channel.title = channel.title or candidate.title
            channel.url = channel.url or candidate.url or f"https://t.me/{normalized}"
            channel.thematic_score = max(channel.thematic_score or 0, candidate.thematic_score or 0)
    else:
        channel = Channel(
            username=normalized,
            title=candidate.title if candidate else None,
            url=(candidate.url if candidate else None) or f"https://t.me/{normalized}",
            status="active",
            thematic_score=candidate.thematic_score if candidate else 0,
        )
        session.add(channel)
    return candidate


def set_channel_candidate_status(session: Session, username: str, status: str) -> ChannelCandidate | None:
    normalized = normalize_channel_username(username)
    candidate = session.query(ChannelCandidate).filter(ChannelCandidate.username == normalized).one_or_none()
    if candidate:
        candidate.status = status
    return candidate


def dedupe_channel_candidates(session: Session) -> int:
    candidates = session.query(ChannelCandidate).all()
    by_username: dict[str, list[ChannelCandidate]] = {}
    for candidate in candidates:
        normalized = normalize_channel_username(candidate.username)
        if normalized != candidate.username:
            candidate.username = normalized
        by_username.setdefault(normalized, []).append(candidate)
    priority = {"approved": 4, "rejected": 3, "pending": 2, "archived": 1}
    removed = 0
    for username, rows in by_username.items():
        if not username or len(rows) <= 1:
            continue
        winner = sorted(rows, key=lambda row: (priority.get(row.status or "pending", 0), row.mentions_count or 0, row.updated_at or row.created_at), reverse=True)[0]
        winner.mentions_count = sum(row.mentions_count or 0 for row in rows) or 1
        winner.thematic_score = max(row.thematic_score or 0 for row in rows)
        winner.status = sorted(rows, key=lambda row: priority.get(row.status or "pending", 0), reverse=True)[0].status
        for row in rows:
            if row.id != winner.id:
                session.delete(row)
                removed += 1
    return removed
