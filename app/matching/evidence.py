from __future__ import annotations

import asyncio

from sqlalchemy.orm import Session

from app.firms.map_render import render_firms_map_html, screenshot_map
from app.models import Case, CaseMatch, EvidenceFile, Message
from app.telegram.screenshots import screenshot_message


def render_evidence(session: Session, include_case_location_maps: bool = False) -> int:
    count = 0
    for match in session.query(CaseMatch).all():
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
    for case in session.query(Case).all():
        if not include_case_location_maps and case.id not in firms_case_ids:
            continue
        html_path = render_firms_map_html(session, case)
        if html_path:
            image_path = asyncio.run(screenshot_map(html_path))
            if image_path:
                session.add(EvidenceFile(case_id=case.id, file_type="firms_map", path=image_path, title="FIRMS map"))
                count += 1
    return count
