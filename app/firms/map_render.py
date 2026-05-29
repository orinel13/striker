from __future__ import annotations

import html
from pathlib import Path

from sqlalchemy.orm import Session

from app.firms.matcher import nearby_firms_points
from app.models import Case, EvidenceFile


def render_firms_map_html(session: Session, case: Case) -> str | None:
    if case.lat is None or case.lon is None:
        return None
    points = nearby_firms_points(session, case)
    if not points:
        return None
    markers = "\n".join(
        f"L.marker([{p.lat},{p.lon}]).addTo(map).bindPopup({html.escape(repr(f'{p.acq_date} {p.acq_time} {p.satellite} confidence={p.confidence} FRP={p.frp}'))});"
        for p in points
    )
    out = Path("data/maps") / f"case_{case.id}_firms.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#map{{height:100%;margin:0}}</style></head><body>
<div id="map"></div><script>
const map = L.map('map').setView([{case.lat}, {case.lon}], 11);
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{maxZoom: 19}}).addTo(map);
L.circle([{case.lat}, {case.lon}], {{radius: {case.radius_km * 1000}, color: '#2563eb', fillOpacity: .08}}).addTo(map);
L.marker([{case.lat}, {case.lon}]).addTo(map).bindPopup('Case location');
{markers}
</script></body></html>""",
        encoding="utf-8",
    )
    session.add(EvidenceFile(case_id=case.id, file_type="firms_map_html", path=str(out), title="FIRMS map"))
    return str(out)


async def screenshot_map(html_path: str) -> str | None:
    output = Path(html_path).with_suffix(".png")
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(viewport={"width": 1200, "height": 800})
            await page.goto(Path(html_path).resolve().as_uri(), wait_until="networkidle", timeout=30000)
            await page.screenshot(path=str(output), full_page=True)
            await browser.close()
        return str(output)
    except Exception:
        return html_path
