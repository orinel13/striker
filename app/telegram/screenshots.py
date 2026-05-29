from __future__ import annotations

import html
from pathlib import Path

from app.models import Channel, EvidenceFile, Message


def public_message_url(channel: Channel, message: Message) -> str | None:
    if not channel.username:
        return None
    return f"https://t.me/s/{channel.username}/{message.tg_message_id}"


def evidence_card_html(channel: Channel, message: Message) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
body{{font-family:Arial,sans-serif;background:#f6f7f9;margin:0;padding:24px}}
.card{{max-width:840px;background:white;border:1px solid #d7dce2;border-radius:8px;padding:20px}}
.meta{{color:#526070;font-size:14px;margin-bottom:12px}} .text{{white-space:pre-wrap;font-size:16px;line-height:1.45}}
</style></head><body><div class="card">
<h2>{html.escape(channel.title or channel.username or "Telegram")}</h2>
<div class="meta">{message.posted_at.isoformat()} | {html.escape(message.url or "")}</div>
<div class="text">{html.escape(message.text)}</div>
</div></body></html>"""


async def screenshot_message(session, message: Message) -> str | None:
    channel = session.get(Channel, message.channel_id)
    if not channel:
        return None
    Path("data/screenshots").mkdir(parents=True, exist_ok=True)
    output = Path("data/screenshots") / f"telegram_{message.id}.png"
    fallback = Path("data/tmp") / f"telegram_{message.id}.html"
    url = public_message_url(channel, message)
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(viewport={"width": 1100, "height": 900})
            try:
                if url:
                    await page.goto(url, wait_until="networkidle", timeout=20000)
                await page.screenshot(path=str(output), full_page=True)
            except Exception:
                fallback.write_text(evidence_card_html(channel, message), encoding="utf-8")
                await page.goto(fallback.resolve().as_uri(), wait_until="load")
                await page.screenshot(path=str(output), full_page=True)
            await browser.close()
        session.add(EvidenceFile(message_id=message.id, file_type="telegram_screenshot", path=str(output)))
        return str(output)
    except Exception:
        fallback.write_text(evidence_card_html(channel, message), encoding="utf-8")
        return str(fallback)

