from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope
from app.models import Channel, Message, MessageKeyword
from app.nlp.extractors import extract_coordinates, extract_time
from app.nlp.keywords import find_keywords
from app.nlp.language import detect_language
from app.nlp.scoring import score_message_relevance
from app.telegram.channel_discovery import record_candidates
from app.telegram.client import TelegramClientFactory
from app.telegram.normalizer import normalize_text, text_sha256

logger = logging.getLogger(__name__)


def _seed_channels() -> list[str]:
    path = Path("data/seed_channels.txt")
    if not path.exists():
        return []
    result = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip().lstrip("@")
        if line and not line.startswith("#"):
            result.append(line)
    return result


def _message_url(username: str | None, message_id: int) -> str | None:
    return f"https://t.me/{username}/{message_id}" if username else None


async def _download_media_if_needed(client, tg_message, relevance: float, username: str) -> str | None:
    if not getattr(tg_message, "media", None) or relevance < 0.45:
        return None
    target_dir = Path("data/media") / username
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        path = await client.download_media(tg_message, file=str(target_dir))
        return str(path) if path else None
    except Exception as exc:
        logger.warning("Media download failed for %s/%s: %s", username, tg_message.id, exc)
        return None


def _upsert_seed_channels(session: Session) -> list[Channel]:
    channels = []
    for username in _seed_channels():
        channel = session.query(Channel).filter(Channel.username == username).one_or_none()
        if not channel:
            channel = Channel(username=username, url=f"https://t.me/{username}", status="active")
            session.add(channel)
            session.flush()
        channels.append(channel)
    channels.extend(session.query(Channel).filter(Channel.status == "active").all())
    unique = {c.username or str(c.id): c for c in channels}
    return list(unique.values())


async def collect_channel(username: str) -> int:
    settings = get_settings()
    factory = TelegramClientFactory()
    saved = 0
    async with factory.create() as client:
        with session_scope() as session:
            channel = session.query(Channel).filter(Channel.username == username).one_or_none()
            if not channel:
                channel = Channel(username=username, url=f"https://t.me/{username}")
                session.add(channel)
                session.flush()
            entity = await client.get_entity(username)
            channel.tg_id = getattr(entity, "id", None)
            channel.title = getattr(entity, "title", None) or getattr(entity, "first_name", None)
            min_id = channel.last_message_id or 0
            try:
                messages = client.iter_messages(entity, min_id=min_id, reverse=True, limit=settings.max_history_batch)
                async for tg_message in messages:
                    text = tg_message.message or ""
                    normalized = normalize_text(text)
                    kw = find_keywords(normalized)
                    has_place = bool(extract_coordinates(text))
                    has_time = bool(extract_time(text))
                    relevance = score_message_relevance(
                        text,
                        has_place=has_place,
                        has_time=has_time,
                        has_media=bool(getattr(tg_message, "media", None)),
                    )
                    media_path = await _download_media_if_needed(client, tg_message, relevance, username)
                    message = Message(
                        channel_id=channel.id,
                        tg_message_id=tg_message.id,
                        posted_at=tg_message.date.replace(tzinfo=None),
                        collected_at=datetime.utcnow(),
                        text=text,
                        normalized_text=normalized,
                        text_hash=text_sha256(normalized),
                        language=detect_language(text),
                        url=_message_url(username, tg_message.id),
                        has_media=bool(getattr(tg_message, "media", None)),
                        media_path=media_path,
                        fwd_from_name=str(getattr(getattr(tg_message, "fwd_from", None), "from_name", "") or "") or None,
                        fwd_from_channel=None,
                        fwd_from_message_id=getattr(getattr(tg_message, "fwd_from", None), "channel_post", None),
                        reply_to_message_id=getattr(getattr(tg_message, "reply_to", None), "reply_to_msg_id", None),
                        raw_json=json.dumps(tg_message.to_dict(), default=str, ensure_ascii=False),
                        relevance_score=relevance,
                    )
                    session.add(message)
                    try:
                        session.flush()
                    except IntegrityError:
                        session.rollback()
                        continue
                    for category, keyword in kw:
                        session.add(MessageKeyword(message_id=message.id, category=category, keyword=keyword))
                    record_candidates(session, message, relevance)
                    channel.last_message_id = max(channel.last_message_id or 0, tg_message.id)
                    saved += 1
                channel.last_collected_at = datetime.utcnow()
            except Exception:
                raise
    return saved


async def collect_once() -> int:
    settings = get_settings()
    with session_scope() as session:
        channels = _upsert_seed_channels(session)
        usernames = [c.username for c in channels if c.username]
    total = 0
    for username in usernames:
        try:
            total += await collect_channel(username)
        except Exception as exc:
            if exc.__class__.__name__ == "FloodWaitError" and hasattr(exc, "seconds"):
                await asyncio.sleep(int(exc.seconds) + 5)
            logger.exception("Collection failed for channel %s: %s", username, exc)
        await asyncio.sleep(settings.telegram_request_sleep_seconds)
    return total


async def collect_loop() -> None:
    settings = get_settings()
    while True:
        await collect_once()
        await asyncio.sleep(settings.collect_interval_seconds)

