from __future__ import annotations

from datetime import date, datetime

from docx import Document

from app.documents.strike_table_parser import DocumentPeriod, parse_docx_strike_rows, parse_time_or_range


def _night_period() -> DocumentPeriod:
    return DocumentPeriod(date(2026, 5, 28), date(2026, 5, 29), True)


def _docx_with_rows(path, rows: list[list[str]]) -> None:
    doc = Document()
    table = doc.add_table(rows=0, cols=2)
    for left, right in rows:
        cells = table.add_row().cells
        cells[0].text = left
        cells[1].text = right
    doc.save(path)


def test_night_period_cross_midnight_range():
    result = parse_time_or_range("22.00-07.30", base_date=None, period=_night_period())
    assert result["time_window_start"] == datetime(2026, 5, 28, 21, 0)
    assert result["time_window_end"] == datetime(2026, 5, 29, 8, 30)


def test_night_period_single_after_midnight():
    result = parse_time_or_range("00.45", base_date=None, period=_night_period())
    assert result["event_time_local"] == "00:45"
    assert result["time_window_start"] == datetime(2026, 5, 28, 23, 45)
    assert result["time_window_end"] == datetime(2026, 5, 29, 1, 45)


def test_night_period_same_morning_range():
    result = parse_time_or_range("01.00-02.00", base_date=None, period=_night_period())
    assert result["time_window_start"] == datetime(2026, 5, 29, 0, 0)
    assert result["time_window_end"] == datetime(2026, 5, 29, 3, 0)


def test_night_period_evening_single_time():
    result = parse_time_or_range("20.10", base_date=None, period=_night_period())
    assert result["time_window_start"] == datetime(2026, 5, 28, 19, 10)
    assert result["time_window_end"] == datetime(2026, 5, 28, 21, 10)


def test_night_period_docx_rows(tmp_path):
    path = tmp_path / "night.docx"
    _docx_with_rows(
        path,
        [
            ["00.45", "Днепропетровская обл.\nн.п. Зеленодольск\n5268180 6549666"],
            ["23.00-\n03.30", "Днепропетровская обл.\nн.п. Днепропетровск\n(6055 4)"],
            ["05.20", "Харьковская обл.\nн.п. Андреевка\n5494133 7328850"],
        ],
    )
    rows = parse_docx_strike_rows(path, period_start=date(2026, 5, 28), period_end=date(2026, 5, 29), night_mode=True)
    assert len(rows) == 3
    assert rows[0].event_date == date(2026, 5, 29)
    assert rows[1].time_window_start == datetime(2026, 5, 28, 22, 0)
    assert rows[1].time_window_end == datetime(2026, 5, 29, 4, 30)
    assert rows[2].event_date == date(2026, 5, 29)

