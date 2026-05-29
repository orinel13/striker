from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz


TME_RE = re.compile(r"https?://t\.me/(?:s/)?(?P<channel>[A-Za-z0-9_]+)/(?P<id>\d+)")


@dataclass
class DedupeCandidate:
    id: int
    text_hash: str
    normalized_text: str
    url: str | None = None
    fwd_from_channel: str | None = None
    fwd_from_message_id: int | None = None


def tme_key(url: str | None) -> tuple[str, str] | None:
    if not url:
        return None
    match = TME_RE.search(url)
    if not match:
        return None
    return match["channel"].lower(), match["id"]


def find_canonical(candidate: DedupeCandidate, existing: list[DedupeCandidate], threshold: int = 94) -> int | None:
    cand_tme = tme_key(candidate.url)
    for item in existing:
        if candidate.text_hash and candidate.text_hash == item.text_hash:
            return item.id
        if cand_tme and cand_tme == tme_key(item.url):
            return item.id
        if (
            candidate.fwd_from_channel
            and item.fwd_from_channel
            and candidate.fwd_from_channel == item.fwd_from_channel
            and candidate.fwd_from_message_id
            and candidate.fwd_from_message_id == item.fwd_from_message_id
        ):
            return item.id
        if fuzz.token_set_ratio(candidate.normalized_text, item.normalized_text) >= threshold:
            return item.id
    return None

