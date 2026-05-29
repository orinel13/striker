from __future__ import annotations

import asyncio
import html
import json
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.shared import Inches
from sqlalchemy.orm import Session

from app.firms.matcher import FIRMS_CAVEAT
from app.matching.case_matcher import localize_message_time
from app.models import Case, CaseMatch, Channel, EvidenceFile, Export, Message
from app.telegram.screenshots import render_evidence_card_png, screenshot_message


REAL_MATCH_TYPES = {"telegram", "firms"}
PRIORITY_ORDER = {"A": 0, "B": 1, "C": 2, "FIRMS+": 3, "FIRMS?": 4}


@dataclass
class PublicationItem:
    publication_number: int | None
    case_ids: list[int]
    place_name: str
    oblast: str | None
    message_id: int
    channel_title: str | None
    channel_username: str | None
    posted_at_local: datetime
    url: str | None
    text: str
    screenshot_path: str | None
    evidence_card_path: str | None
    priority: str
    total_score: float
    match_explanation: str


def _export_dir() -> Path:
    path = Path("data/exports") / datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path.mkdir(parents=True, exist_ok=True)
    return path


def real_case_matches(session: Session, case_id: int) -> list[CaseMatch]:
    return (
        session.query(CaseMatch)
        .filter(CaseMatch.case_id == case_id, CaseMatch.match_type.in_(REAL_MATCH_TYPES))
        .order_by(CaseMatch.total_score.desc())
        .all()
    )


def _all_case_matches(session: Session, case_id: int) -> list[CaseMatch]:
    return session.query(CaseMatch).filter(CaseMatch.case_id == case_id).order_by(CaseMatch.total_score.desc()).all()


def telegram_matches_for_case(session: Session, case_id: int, include_pending: bool = False) -> list[tuple[CaseMatch, Message]]:
    rows: list[tuple[CaseMatch, Message]] = []
    statuses = ["approved", "auto_approved"] + (["pending"] if include_pending else [])
    matches = (
        session.query(CaseMatch)
        .filter(CaseMatch.case_id == case_id, CaseMatch.message_id.isnot(None), CaseMatch.review_status.in_(statuses))
        .all()
    )
    for match in matches:
        message = session.get(Message, match.message_id)
        if message:
            rows.append((match, message))
    return sorted(rows, key=lambda row: (PRIORITY_ORDER.get(row[0].priority, 99), localize_message_time(row[1].posted_at), -row[0].total_score))


def _case_place(case: Case) -> str:
    return case.place_name or case.reference_text or "Неустановленный населённый пункт"


def build_publication_items(session: Session, include_pending: bool = False) -> list[PublicationItem]:
    items_by_key: dict[tuple[str, int], PublicationItem] = {}
    order: list[tuple[str, int]] = []
    for case in session.query(Case).order_by(Case.id).all():
        place_name = _case_place(case)
        for match, message in telegram_matches_for_case(session, case.id, include_pending=include_pending):
            dedupe_id = message.canonical_message_id or message.id
            key = (place_name, dedupe_id)
            channel = session.get(Channel, message.channel_id)
            if key not in items_by_key:
                items_by_key[key] = PublicationItem(
                    publication_number=None,
                    case_ids=[case.id],
                    place_name=place_name,
                    oblast=case.oblast,
                    message_id=message.id,
                    channel_title=channel.title if channel else None,
                    channel_username=channel.username if channel else None,
                    posted_at_local=localize_message_time(message.posted_at),
                    url=message.url,
                    text=message.text,
                    screenshot_path=None,
                    evidence_card_path=None,
                    priority=match.priority,
                    total_score=match.total_score,
                    match_explanation=match.explanation,
                )
                order.append(key)
            elif case.id not in items_by_key[key].case_ids:
                items_by_key[key].case_ids.append(case.id)
    grouped_keys = sorted(order, key=lambda key: (items_by_key[key].place_name, order.index(key)))
    items: list[PublicationItem] = []
    for number, key in enumerate(grouped_keys, start=1):
        item = items_by_key[key]
        item.publication_number = number
        items.append(item)
    return items


def ensure_publication_screenshot(session: Session, item: PublicationItem) -> str | None:
    message = session.get(Message, item.message_id)
    if not message:
        return None
    existing = (
        session.query(EvidenceFile)
        .filter(EvidenceFile.message_id == message.id, EvidenceFile.file_type.in_(["telegram_screenshot", "telegram_card"]))
        .order_by(EvidenceFile.created_at.desc())
        .all()
    )
    for evidence in existing:
        if evidence.path and evidence.path.lower().endswith(".png") and Path(evidence.path).exists():
            if evidence.file_type == "telegram_card":
                item.evidence_card_path = evidence.path
            else:
                item.screenshot_path = evidence.path
            return evidence.path
    try:
        path = asyncio.run(screenshot_message(session, message))
    except RuntimeError:
        path = None
    if path and path.lower().endswith(".png") and Path(path).exists():
        item.screenshot_path = path
        return path
    try:
        path = asyncio.run(render_evidence_card_png(session, message, case_id=item.case_ids[0] if item.case_ids else None))
    except RuntimeError:
        path = None
    if path and Path(path).exists():
        item.evidence_card_path = path
        return path
    return None


def _unmatched_cases(session: Session, include_pending: bool = False) -> list[Case]:
    return [case for case in session.query(Case).order_by(Case.id).all() if not telegram_matches_for_case(session, case.id, include_pending=include_pending)]


def _add_no_publications_appendix(doc: Document, cases: list[Case]) -> None:
    if not cases:
        return
    doc.add_heading("Кейсы без найденных публикаций", level=1)
    table = doc.add_table(rows=1, cols=4)
    for idx, title in enumerate(["№", "Дата", "Населённый пункт", "Описание"]):
        table.rows[0].cells[idx].text = title
    for case in cases:
        row = table.add_row().cells
        row[0].text = str(case.id)
        row[1].text = case.event_date.isoformat() if case.event_date else ""
        row[2].text = _case_place(case)
        row[3].text = case.raw_text[:500]


def build_osint_docx_report(session: Session, out_path: Path, include_pending: bool = False) -> None:
    doc = Document()
    doc.add_heading("OSINT-подборка подтверждающих публикаций", 0)
    doc.add_paragraph("Автоматическая ретроспективная подборка из Telegram-архива. Не является live tracking.")
    items = build_publication_items(session, include_pending=include_pending)
    if not items:
        doc.add_paragraph("По загруженным кейсам не найдено Telegram-публикаций, удовлетворяющих критериям сопоставления.")
        _add_no_publications_appendix(doc, session.query(Case).order_by(Case.id).all())
        doc.save(out_path)
        return
    current_place: str | None = None
    for item in items:
        if item.place_name != current_place:
            current_place = item.place_name
            doc.add_heading(item.place_name, level=1)
        paragraph = doc.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run(f"Публикация №{item.publication_number}")
        run.bold = True
        doc.add_paragraph().add_run("OSINT").italic = True
        date_paragraph = doc.add_paragraph()
        date_run = date_paragraph.add_run(f"{item.posted_at_local:%d.%m.%Y} г.")
        date_run.bold = True
        date_run.font.highlight_color = WD_COLOR_INDEX.YELLOW
        source = "Telegram"
        if item.channel_title:
            source += f", {item.channel_title}"
        if item.channel_username:
            source += f" (@{item.channel_username})"
        doc.add_paragraph(f"Источник: {source}")
        doc.add_paragraph(f"Время публикации: {item.posted_at_local:%H:%M}")
        if item.url:
            doc.add_paragraph(f"Ссылка: {item.url}")
        screenshot_path = ensure_publication_screenshot(session, item)
        material = "фотоматериал." if screenshot_path else "ссылка на публикацию."
        material_paragraph = doc.add_paragraph()
        material_paragraph.add_run(f"Подтверждающий материал: {material}").italic = True
        if screenshot_path and Path(screenshot_path).exists():
            try:
                doc.add_picture(screenshot_path, width=Inches(6.0))
            except Exception:
                pass
        if item.text:
            doc.add_paragraph("Текст публикации:").runs[0].bold = True
            doc.add_paragraph(item.text)
        doc.add_paragraph(f"Относится к кейсам: №{', №'.join(str(case_id) for case_id in item.case_ids)}")
        doc.add_paragraph("")
    _add_no_publications_appendix(doc, _unmatched_cases(session, include_pending=include_pending))
    doc.save(out_path)


def build_osint_html_report(session: Session, out_path: Path, include_pending: bool = False) -> None:
    items = build_publication_items(session, include_pending=include_pending)
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'><title>OSINT report</title>",
        "<style>body{font-family:Arial,sans-serif;margin:32px;line-height:1.45}.pub{margin:28px 0}.num{text-align:center;font-weight:700}.osint{font-style:italic}.date{font-weight:700;background:#fff59d;display:inline-block;padding:2px 4px}img{max-width:760px;width:100%;border:1px solid #d6dde6}</style>",
        "</head><body><h1>OSINT-подборка подтверждающих публикаций</h1>",
        "<p>Автоматическая ретроспективная подборка из Telegram-архива. Не является live tracking.</p>",
    ]
    if not items:
        parts.append("<p>По загруженным кейсам не найдено Telegram-публикаций, удовлетворяющих критериям сопоставления.</p>")
    current_place = None
    for item in items:
        if item.place_name != current_place:
            current_place = item.place_name
            parts.append(f"<h2>{html.escape(item.place_name)}</h2>")
        screenshot_path = ensure_publication_screenshot(session, item)
        parts.append(f"<section class='pub'><p class='num'>Публикация №{item.publication_number}</p>")
        parts.append("<p class='osint'>OSINT</p>")
        parts.append(f"<p><span class='date'>{item.posted_at_local:%d.%m.%Y} г.</span></p>")
        source = "Telegram"
        if item.channel_title:
            source += f", {item.channel_title}"
        if item.channel_username:
            source += f" (@{item.channel_username})"
        parts.append(f"<p>Источник: {html.escape(source)}</p><p>Время публикации: {item.posted_at_local:%H:%M}</p>")
        if item.url:
            parts.append(f"<p>Ссылка: <a href='{html.escape(item.url)}'>{html.escape(item.url)}</a></p>")
        parts.append(f"<p><em>Подтверждающий материал: {'фотоматериал.' if screenshot_path else 'ссылка на публикацию.'}</em></p>")
        if screenshot_path and Path(screenshot_path).exists():
            parts.append(f"<img src='{html.escape(Path(screenshot_path).as_posix())}' alt='publication evidence'>")
        if item.text:
            parts.append(f"<p><strong>Текст публикации:</strong></p><p>{html.escape(item.text).replace(chr(10), '<br>')}</p>")
        parts.append(f"<p>Относится к кейсам: №{', №'.join(str(case_id) for case_id in item.case_ids)}</p></section>")
    unmatched = _unmatched_cases(session, include_pending=include_pending)
    if unmatched:
        parts.append("<h2>Кейсы без найденных публикаций</h2><ul>")
        for case in unmatched:
            parts.append(f"<li>№{case.id}: {html.escape(_case_place(case))} — {html.escape(case.raw_text[:300])}</li>")
        parts.append("</ul>")
    parts.append("</body></html>")
    out_path.write_text("\n".join(parts), encoding="utf-8")


def build_technical_docx_report(session: Session, out_path: Path) -> None:
    doc = Document()
    doc.add_heading("Striker technical report", 0)
    doc.add_paragraph("Technical diagnostics for cases, coordinates, FIRMS context and matching scores.")
    doc.add_paragraph(FIRMS_CAVEAT)
    cases = session.query(Case).order_by(Case.id).all()
    table = doc.add_table(rows=1, cols=7)
    for idx, title in enumerate(["Case", "Date", "Oblast", "Place/reference", "WGS84", "Coord source", "Real matches"]):
        table.rows[0].cells[idx].text = title
    for case in cases:
        row = table.add_row().cells
        row[0].text = str(case.id)
        row[1].text = case.event_date.isoformat() if case.event_date else ""
        row[2].text = case.oblast or ""
        row[3].text = case.place_name or case.reference_text or ""
        row[4].text = f"{case.lat}, {case.lon}" if case.lat is not None and case.lon is not None else ""
        row[5].text = case.coordinate_source or ""
        row[6].text = str(len(real_case_matches(session, case.id)))
    for case in cases:
        doc.add_page_break()
        doc.add_heading(f"Case {case.id}", level=1)
        doc.add_paragraph(case.raw_text)
        details = doc.add_table(rows=1, cols=2)
        details.rows[0].cells[0].text = "Field"
        details.rows[0].cells[1].text = "Value"
        for title, value in [
            ("Oblast", case.oblast),
            ("Place/reference", case.place_name or case.reference_text),
            ("Reference text", case.reference_text),
            ("Raw grid northing", case.raw_grid_northing),
            ("Raw grid easting", case.raw_grid_easting),
            ("Coordinate source", case.coordinate_source),
            ("WGS84 lat/lon", f"{case.lat}, {case.lon}" if case.lat is not None and case.lon is not None else None),
            ("Parser warnings", case.parser_warnings),
        ]:
            if value:
                row = details.add_row().cells
                row[0].text = title
                row[1].text = str(value)
        matches = _all_case_matches(session, case.id)
        mt = doc.add_table(rows=1, cols=6)
        for idx, title in enumerate(["Type", "Priority", "Total", "Time", "Geo", "Explanation"]):
            mt.rows[0].cells[idx].text = title
        for match in matches:
            row = mt.add_row().cells
            row[0].text = match.match_type
            row[1].text = match.priority
            row[2].text = str(match.total_score)
            row[3].text = str(match.time_score)
            row[4].text = str(match.geo_score)
            row[5].text = match.explanation
        for evidence in session.query(EvidenceFile).filter(EvidenceFile.case_id == case.id).all():
            if evidence.file_type == "firms_map" and evidence.path.lower().endswith(".png") and Path(evidence.path).exists():
                doc.add_paragraph("Карта района поиска по исходным координатам, не доказательство события.")
                try:
                    doc.add_picture(evidence.path, width=Inches(6.5))
                except Exception:
                    doc.add_paragraph(f"Evidence file: {evidence.path}")
    doc.save(out_path)


def build_technical_html_report(session: Session, out_path: Path) -> None:
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'><title>Technical report</title>",
        "<style>body{font-family:Arial,sans-serif;margin:32px;line-height:1.45} table{border-collapse:collapse;width:100%;margin:12px 0} td,th{border:1px solid #ccd2da;padding:6px;vertical-align:top}</style>",
        "</head><body><h1>Striker technical report</h1>",
        f"<p>{html.escape(FIRMS_CAVEAT)}</p>",
    ]
    for case in session.query(Case).order_by(Case.id).all():
        parts.append(f"<h2>Case {case.id}</h2><p>{html.escape(case.raw_text)}</p>")
        parts.append("<table><tr><th>Type</th><th>Priority</th><th>Total</th><th>Explanation</th></tr>")
        for match in _all_case_matches(session, case.id):
            parts.append(f"<tr><td>{match.match_type}</td><td>{match.priority}</td><td>{match.total_score}</td><td>{html.escape(match.explanation)}</td></tr>")
        parts.append("</table>")
    parts.append("</body></html>")
    out_path.write_text("\n".join(parts), encoding="utf-8")


def build_zip(session: Session, export_dir: Path, source_docx: str | None) -> Path:
    zip_path = export_dir / "evidence.zip"
    metadata = {
        "created_at": datetime.utcnow().isoformat(),
        "cases": [case.id for case in session.query(Case).all()],
        "caveat": FIRMS_CAVEAT,
    }
    (export_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    if source_docx and Path(source_docx).exists():
        source_dir = export_dir / "source_docx_copy"
        source_dir.mkdir(exist_ok=True)
        shutil.copy2(source_docx, source_dir / Path(source_docx).name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in export_dir.rglob("*"):
            if file.is_file() and file != zip_path:
                zf.write(file, file.relative_to(export_dir).as_posix())
        for folder in ["data/screenshots", "data/maps"]:
            base = Path(folder)
            if base.exists():
                for path in base.glob("*"):
                    if path.is_file():
                        zf.write(path, f"{base.name}/{path.name}")
    return zip_path


def export_report(
    session: Session,
    job_id: int | None = None,
    source_docx: str | None = None,
    style: str = "osint",
    include_technical_appendix: bool = True,
    include_pending: bool = False,
) -> Export:
    export_dir = _export_dir()
    docx_path = export_dir / "report.docx"
    html_path = export_dir / "report.html"
    if style == "technical":
        build_technical_docx_report(session, docx_path)
        build_technical_html_report(session, html_path)
    else:
        build_osint_docx_report(session, docx_path, include_pending=include_pending)
        build_osint_html_report(session, html_path, include_pending=include_pending)
        if include_technical_appendix:
            build_technical_docx_report(session, export_dir / "technical_report.docx")
            build_technical_html_report(session, export_dir / "technical_report.html")
    zip_path = build_zip(session, export_dir, source_docx)
    export = Export(
        job_id=job_id,
        title="Striker OSINT evidence report" if style == "osint" else "Striker technical report",
        docx_path=str(docx_path),
        html_path=str(html_path),
        zip_path=str(zip_path),
    )
    session.add(export)
    session.flush()
    return export
