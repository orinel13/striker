from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import ChannelCandidate, Message


TME_CHANNEL_RE = re.compile(r"(?:https?://t\.me/|@)(?P<username>[A-Za-z][A-Za-z0-9_]{3,31})(?!/\d)")


def extract_channel_usernames(text: str) -> set[str]:
    ignored = {"share", "s"}
    return {m["username"].lower() for m in TME_CHANNEL_RE.finditer(text or "") if m["username"].lower() not in ignored}


def record_candidates(session: Session, message: Message, thematic_score: float) -> int:
    usernames = extract_channel_usernames(message.text)
    if message.fwd_from_channel:
        usernames.add(message.fwd_from_channel.lower().lstrip("@"))
    count = 0
    for username in usernames:
        existing = (
            session.query(ChannelCandidate)
            .filter(ChannelCandidate.username == username, ChannelCandidate.status == "pending")
            .one_or_none()
        )
        if existing:
            existing.mentions_count += 1
            existing.thematic_score = max(existing.thematic_score, thematic_score)
        else:
            session.add(
                ChannelCandidate(
                    username=username,
                    url=f"https://t.me/{username}",
                    source_channel_id=message.channel_id,
                    first_seen_message_id=message.tg_message_id,
                    thematic_score=thematic_score,
                )
            )
        count += 1
    return count

