# -*- coding: utf-8 -*-
"""Тесты импорта .xls (xlrd) и вспомогательных функций."""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.xls_importer import (
    import_xls, detect_period, _to_float, _to_str, COL_SUM, COL_NORM,  # noqa: F401
    create_manual_schedule, serialize_result, deserialize_result, EmployeeRow,
)
from app.services.time_parser import parse_cell


# --- вспомогательные ------------------------------------------------------- #
def test_to_float():
    assert _to_float(None) is None
    assert _to_float("") is None
    assert _to_float("60") == 60.0
    assert _to_float("60,5") == 60.5
    assert _to_float(131.0) == 131.0
    assert _to_float("abc") is None


def test_to_str():
    assert _to_str(None) == ""
    assert _to_str(" В ") == "В"


# --- импорт реальных файлов (пропуск, если файлов нет в репозитории) -------- #
FILES = [
    ("ноябрь  2026  общий.xls", 79, {33: 18, 39: 36, 36: 4, 40: 20, None: 1}),
    ("ноябрь  УПО 2026.xls", 17, {39: 17}),
]


def test_import_real_files():
    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fn, nrows, norm_dist in FILES:
        path = os.path.join(BASE, fn)
        if not os.path.exists(path):
            continue  # .xls не в git, только локально
        res = import_xls(path)
        assert (res.year, res.month) == (2026, 11), "%s период" % fn
        assert res.day_count == 30, "%s дней" % fn
        assert len(res.rows) == nrows, "%s строк" % fn
        got_dist = dict(Counter(r.week_norm for r in res.rows))
        assert got_dist == norm_dist, "%s распределение норм" % fn

        by_name = {r.name: r for r in res.rows}
        for nm, exp_sum, exp_norm in [("Азарнова Е.С.", 131.0, 131.0)]:
            if nm in by_name:
                assert round(by_name[nm].total_hours, 1) == exp_sum, "%s: %s часов" % (fn, nm)
                assert by_name[nm].norm_col == exp_norm, "%s: %s норма" % (fn, nm)


# --- ручной график: создание и сериализация --------------------------------- #
def test_manual_schedule_and_serialize():
    res = create_manual_schedule(2026, 11)
    assert res.manual is True
    assert res.year == 2026
    assert res.month == 11
    assert res.day_count == 30
    assert res.rows == []

    row = EmployeeRow(index=0, name="Смирнова О.А.", position="зубной врач",
                      rate=0.5, week_norm=33)
    row.raw_cells[2] = "8-15,48"
    row.parsed[2] = parse_cell("8-15,48")
    row.total_hours = 7.8
    res.rows.append(row)

    data = serialize_result(res)
    assert len(data["employees"]) == 1
    assert data["employees"][0]["rate"] == 0.5
    assert data["employees"][0]["week_norm"] == 33
    assert data["employees"][0]["days"] == {"2": "8-15,48"}

    res2 = deserialize_result(data)
    assert res2.rows[0].name == "Смирнова О.А."
    assert res2.rows[0].rate == 0.5
    assert res2.rows[0].week_norm == 33
    assert round(res2.rows[0].total_hours, 1) == 7.8
    assert res2.manual is True
