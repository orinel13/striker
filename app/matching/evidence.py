from __future__ import annotations

import asyncio

from sqlalchemy.orm import Session

from app.firms.map_render import render_firms_map_html, screenshot_map
from app.models import Case, CaseMatch, EvidenceFile, Message
from app.telegram.screenshots import screenshot_message


def render_evidence(session: Session, include_case_location_maps: bool = False, include_pending: bool = False, batch_id: int | None = None) -> int:
    count = 0
    query = session.query(CaseMatch).filter(CaseMatch.match_type == "telegram", CaseMatch.message_id.isnot(None))
    statuses = ["approved", "auto_approved"] + (["pending"] if include_pending else [])
    query = query.filter(CaseMatch.review_status.in_(statuses))
    if batch_id is not None:
        query = query.join(Case, Case.id == CaseMatch.case_id).filter(Case.batch_id == batch_id)
    for match in query.all():
        if match.message_id:
            message = session.get(Message, match.message_id)
            if message:
                path = asyncio.run(screenshot_message(session, message))
                count += 1 if path else 0
    firms_case_ids = {
        row[0]
        for row in session.query(CaseMatch.case_id)
        .filter(CaseMatch.match_type == "firms", CaseMatch.firms_point_id.isnot(None))
        .all()
    }
    case_query = session.query(Case)
    if batch_id is not None:
        case_query = case_query.filter(Case.batch_id == batch_id)
    for case in case_query.all():
        if not include_case_location_maps and case.id not in firms_case_ids:
            continue
        html_path = render_firms_map_html(session, case)
        if html_path:
            image_path = asyncio.run(screenshot_map(html_path))
            if image_path:
                session.add(EvidenceFile(batch_id=case.batch_id, case_id=case.id, file_type="firms_map", path=image_path, title="FIRMS map"))
                count += 1
    return count
