from __future__ import annotations

from datetime import date, datetime

from docx import Document

from app.documents.docx_importer import import_docx
from app.documents.strike_table_parser import parse_docx_strike_rows


def _docx_with_rows(path, rows: list[list[str]]) -> None:
    doc = Document()
    table = doc.add_table(rows=0, cols=2)
    for left, right in rows:
        cells = table.add_row().cells
        cells[0].text = left
        cells[1].text = right
    doc.save(path)


def test_midnight_time_range_window(tmp_path):
    path = tmp_path / "midnight.docx"
    _docx_with_rows(
        path,
        [["23.00-\n03.30", "Днепропетровская обл.\nн.п. Днепропетровск\n(6055 4)"]],
    )
    rows = parse_docx_strike_rows(path, document_date=date(2026, 5, 20))
    assert rows[0].event_date == date(2026, 5, 20)
    assert rows[0].time_range_start == "23:00"
    assert rows[0].time_range_end == "03:30"
    assert rows[0].time_window_start == datetime(2026, 5, 20, 22, 0)
    assert rows[0].time_window_end == datetime(2026, 5, 21, 4, 30)


def test_sk42_gauss_kruger_coordinates_and_alias(tmp_path):
    path = tmp_path / "sk42.docx"
    _docx_with_rows(
        path,
        [["05.20", "ДНР\nн.п. Славянск\n(1595 4)\n5415616 7395885"]],
    )
    rows = parse_docx_strike_rows(path, document_date=date(2026, 5, 20))
    assert "Слов" in (rows[0].place_name_raw or "") or "Славянск" in (rows[0].place_name_raw or "")
    assert rows[0].lat == pytest_approx(48.8643)
    assert rows[0].lon == pytest_approx(37.5794)
    assert rows[0].coordinate_source == "sk42_gauss_kruger_zone_7"


def test_short_date_and_time_in_first_cell(tmp_path):
    path = tmp_path / "short-date.docx"
    _docx_with_rows(
        path,
        [["20.05,\n20.10", "Харьковская обл.\n1,2 км с-в. Новая Семеновка\n(52 км ю-з. Харьков)\n5481563 7289651"]],
    )
    rows = parse_docx_strike_rows(path, default_year=2026)
    assert rows[0].event_date == date(2026, 5, 20)
    assert rows[0].event_time_local == "20:10"
    assert rows[0].lat is not None
    assert rows[0].lon is not None


def test_table_rows_are_not_lost(tmp_path):
    path = tmp_path / "three.docx"
    _docx_with_rows(
        path,
        [
            ["21.00-22.00", "Черниговская обл.\nн.п. Чернигов\n(1483 8)"],
            ["21.00-22.00", "Черниговская обл.\nн.п. Прилуки\n(123 км ю-в. Чернигов)\n(0551 5)"],
            ["00.00-\n01.00", "Днепропетровская обл.\nн.п. Васильковка\n5345655 7280503"],
        ],
    )
    rows = parse_docx_strike_rows(path, document_date=date(2026, 5, 20))
    assert len(rows) == 3


def test_import_docx_creates_case_per_non_empty_table_row(session, tmp_path):
    path = tmp_path / "import.docx"
    _docx_with_rows(
        path,
        [
            ["21.00-22.00", "Черниговская обл.\nн.п. Чернигов\n(1483 8)"],
            ["21.00-22.00", "Черниговская обл.\nн.п. Прилуки\n(123 км ю-в. Чернигов)\n(0551 5)"],
            ["00.00-\n01.00", "Днепропетровская обл.\nн.п. Васильковка\n5345655 7280503"],
        ],
    )
    cases = import_docx(session, path, document_date=date(2026, 5, 20))
    assert len(cases) == 3
    assert cases[2].lat == pytest_approx(48.2060)


def pytest_approx(value: float):
    import pytest

    return pytest.approx(value, abs=0.001)

