from __future__ import annotations

from app.config import ConfigError, get_settings


class TelegramClientFactory:
    def __init__(self):
        self.settings = get_settings()

    def create(self):
        if not self.settings.telegram_api_id or not self.settings.telegram_api_hash:
            raise ConfigError("Missing TELEGRAM_API_ID or TELEGRAM_API_HASH")
        from telethon import TelegramClient

        return TelegramClient(
            self.settings.telegram_session_name,
            int(self.settings.telegram_api_id),
            self.settings.telegram_api_hash,
        )

