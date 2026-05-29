from __future__ import annotations

import hmac
import secrets
from pathlib import Path

import bcrypt
from fastapi import Header, HTTPException, Request, UploadFile, status

from app.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def verify_bearer_value(header_value: str | None, expected_token: str) -> bool:
    if not header_value or not expected_token:
        return False
    prefix = "Bearer "
    if not header_value.startswith(prefix):
        return False
    return hmac.compare_digest(header_value[len(prefix) :], expected_token)


def require_api_auth(authorization: str | None = Header(default=None)) -> None:
    if not verify_bearer_value(authorization, get_settings().api_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def ensure_csrf(request: Request, token: str | None) -> None:
    expected = request.session.get("csrf_token")
    if not expected or not token or not hmac.compare_digest(expected, token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


def sanitize_filename(filename: str) -> str:
    keep = [c if c.isalnum() or c in ("-", "_", ".") else "_" for c in Path(filename).name]
    return "".join(keep).strip("._") or "upload.docx"


async def validate_docx_upload(file: UploadFile, max_mb: int) -> bytes:
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only .docx uploads are accepted")
    data = await file.read()
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Upload exceeds {max_mb} MB")
    if not data.startswith(b"PK"):
        raise HTTPException(status_code=400, detail="Invalid .docx file")
    return data

