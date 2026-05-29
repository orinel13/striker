from docx import Document

from app.documents.docx_importer import import_docx
from app.models import Place


def test_docx_importer_extracts_case(session, tmp_path):
    session.add(Place(name="Київ", name_uk="Київ", name_ru="Киев", lat=50.45, lon=30.52))
    session.commit()
    path = tmp_path / "strikes.docx"
    doc = Document()
    doc.add_paragraph("12.05.2024 о 03:15 удар біля Київ, координати 50.450, 30.520")
    doc.save(path)
    cases = import_docx(session, path)
    assert len(cases) == 1
    assert cases[0].event_date.isoformat() == "2024-05-12"
    assert cases[0].event_time_local == "03:15"
    assert cases[0].lat == 50.45
    assert cases[0].time_window_start.hour == 2

