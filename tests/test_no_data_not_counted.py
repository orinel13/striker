from app.documents.report_exporter import real_case_matches
from app.models import Case, CaseMatch


def test_no_data_match_is_not_real_match(session):
    case = Case(raw_text="empty")
    session.add(case)
    session.flush()
    session.add(CaseMatch(case_id=case.id, match_type="none", priority="NO DATA", explanation="nothing"))
    session.commit()
    assert real_case_matches(session, case.id) == []

