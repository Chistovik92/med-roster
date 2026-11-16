# -*- coding: utf-8 -*-
"""Экспорт .xls и повторный импорт, включая 31-й день и подразделение."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.exporter import export_xls
from app.services.time_parser import parse_cell
from app.services.xls_importer import (
    EmployeeRow, ImportResult, import_xls, serialize_result, deserialize_result,
)


def _make_row():
    row = EmployeeRow(index=12, name="Иванова И.И.", position="вр.пед.уч.",
                      rate=0.5, week_norm=39, norm_col=77.5)
    row.raw_cells[1] = "8-15,48"
    row.raw_cells[31] = "12,12-20"
    row.parsed[1] = parse_cell(row.raw_cells[1])
    row.parsed[31] = parse_cell(row.raw_cells[31])
    row.total_hours = sum(p.total_hours for p in row.parsed.values())
    return row


def test_xls_roundtrip():
    row = _make_row()
    original = ImportResult(source="test", year=2026, month=12, day_count=31,
                            department="УПО", rows=[row])

    content = export_xls(original, org="ГУЗ «СГП № 16»", dept="УПО")
    assert content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    restored = import_xls(content, year=2026, month=12)
    assert len(restored.rows) == 1
    saved = restored.rows[0]
    assert saved.name == row.name
    assert saved.rate == 0.5
    assert saved.raw_cells[1] == "8-15,48"
    assert saved.raw_cells[31] == "12,12-20"
    assert saved.sum_col == 15.6
    assert saved.norm_col == 77.5


def test_serialize_department():
    row = _make_row()
    original = ImportResult(source="test", year=2026, month=12, day_count=31,
                            department="УПО", rows=[row])
    payload = serialize_result(original)
    assert payload["department"] == "УПО"
    assert deserialize_result(payload).department == "УПО"
