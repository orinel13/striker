from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    pass


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value in (None, "") else int(value)


def _float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value in (None, "") else float(value)


@dataclass(frozen=True)
class Settings:
    app_env: str
    app_db_path: Path
    app_base_url: str
    app_secret_key: str
    admin_username: str
    admin_password_hash: str
    api_token: str
    telegram_api_id: str
    telegram_api_hash: str
    telegram_session_name: str
    min_archive_delay_minutes: int
    collect_interval_seconds: int
    telegram_request_sleep_seconds: int
    max_history_batch: int
    telegram_archive_days: int
    match_max_per_case: int
    firms_map_key: str
    firms_default_radius_km: float
    local_timezone: str
    web_host: str
    web_port: int
    upload_max_mb: int
    export_retention_days: int
    job_poll_seconds: int

    @property
    def secure_cookies(self) -> bool:
        return self.app_base_url.lower().startswith("https://")


def get_settings() -> Settings:
    _load_dotenv()
    return Settings(
        app_env=os.getenv("APP_ENV", "production"),
        app_db_path=Path(os.getenv("APP_DB_PATH", "data/osint.sqlite3")),
        app_base_url=os.getenv("APP_BASE_URL", ""),
        app_secret_key=os.getenv("APP_SECRET_KEY", ""),
        admin_username=os.getenv("ADMIN_USERNAME", "admin"),
        admin_password_hash=os.getenv("ADMIN_PASSWORD_HASH", ""),
        api_token=os.getenv("API_TOKEN", ""),
        telegram_api_id=os.getenv("TELEGRAM_API_ID", ""),
        telegram_api_hash=os.getenv("TELEGRAM_API_HASH", ""),
        telegram_session_name=os.getenv("TELEGRAM_SESSION_NAME", "data/telegram.session"),
        min_archive_delay_minutes=_int("MIN_ARCHIVE_DELAY_MINUTES", 60),
        collect_interval_seconds=_int("COLLECT_INTERVAL_SECONDS", 900),
        telegram_request_sleep_seconds=_int("TELEGRAM_REQUEST_SLEEP_SECONDS", 3),
        max_history_batch=_int("MAX_HISTORY_BATCH", 100),
        telegram_archive_days=_int("TELEGRAM_ARCHIVE_DAYS", 3),
        match_max_per_case=_int("MATCH_MAX_PER_CASE", 5),
        firms_map_key=os.getenv("FIRMS_MAP_KEY", ""),
        firms_default_radius_km=_float("FIRMS_DEFAULT_RADIUS_KM", 15),
        local_timezone=os.getenv("LOCAL_TIMEZONE", "Europe/Kyiv"),
        web_host=os.getenv("WEB_HOST", "127.0.0.1"),
        web_port=_int("WEB_PORT", 8088),
        upload_max_mb=_int("UPLOAD_MAX_MB", 50),
        export_retention_days=_int("EXPORT_RETENTION_DAYS", 30),
        job_poll_seconds=_int("JOB_POLL_SECONDS", 2),
    )


def require_web_secrets(settings: Settings | None = None) -> Settings:
    settings = settings or get_settings()
    missing = []
    if not settings.app_secret_key:
        missing.append("APP_SECRET_KEY")
    if not settings.admin_password_hash:
        missing.append("ADMIN_PASSWORD_HASH")
    if missing:
        raise ConfigError("Missing required web secret(s): " + ", ".join(missing))
    return settings


def require_api_token(settings: Settings | None = None) -> Settings:
    settings = settings or get_settings()
    if not settings.api_token:
        raise ConfigError("Missing required API secret: API_TOKEN")
    return settings


def ensure_data_dirs() -> None:
    for path in [
        "data",
        "data/inbox",
        "data/exports",
        "data/media",
        "data/screenshots",
        "data/maps",
        "data/tmp",
    ]:
        Path(path).mkdir(parents=True, exist_ok=True)
