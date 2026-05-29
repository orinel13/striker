from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
SPACE_RE = re.compile(r"\s+")
URL_RE = re.compile(r"https?://[^\s)>\]]+")
TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"fbclid", "gclid", "yclid", "mc_cid", "mc_eid"}


def strip_tracking_query(url: str) -> str:
    parts = urlsplit(url)
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k not in TRACKING_KEYS and not k.startswith(TRACKING_PREFIXES)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def normalize_text(text: str) -> str:
    text = INVISIBLE_RE.sub("", text or "")
    text = text.replace("ё", "е").replace("Ё", "е").lower()
    text = URL_RE.sub(lambda m: strip_tracking_query(m.group(0)), text)
    return SPACE_RE.sub(" ", text).strip()


def text_sha256(normalized_text: str) -> str:
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()

