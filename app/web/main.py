from __future__ import annotations

import sys

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.db import init_db
from app.web.routes import router


settings = get_settings()
missing_secrets = [
    name
    for name, value in {
        "APP_SECRET_KEY": settings.app_secret_key,
        "ADMIN_PASSWORD_HASH": settings.admin_password_hash,
        "API_TOKEN": settings.api_token,
    }.items()
    if not value
]
if missing_secrets:
    print("Configuration error: missing required secret(s): " + ", ".join(missing_secrets), file=sys.stderr)

app = FastAPI(title="Striker")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.app_secret_key or "missing-secret-configure-env",
    same_site="lax",
    https_only=settings.secure_cookies,
)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
app.include_router(router)


@app.on_event("startup")
def startup() -> None:
    init_db()
