# -*- coding: utf-8 -*-
"""Тесты планирования (автосмены, копирование графика)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.xls_importer import ImportResult, EmployeeRow
from app.services.time_parser import parse_cell
from app.services.scheduler import autofill, copy_schedule, generate_month


def mk_row(index, name, position, days=None, week_norm=39, rate=1.0):
    row = EmployeeRow(index=index, name=name, position=position,
                      rate=rate, week_norm=week_norm)
    if days:
        for d, val in days.items():
            row.raw_cells[d] = val
            row.parsed[d] = parse_cell(val)
    row.total_hours = sum(p.total_hours for p in row.parsed.values())
    return row


def res_for(rows, year=2026, month=11, day_count=30):
    return ImportResult(source="synthetic.xls", year=year, month=month,
                        day_count=day_count, rows=rows)


def test_autofill_first_employee_index_zero():
    """Регрессия: первый сотрудник имеет index=0, операции не должны его пропускать."""
    res = res_for([mk_row(0, "Первый", "зубной врач", week_norm=33)])
    autofill(res, 0, "8-15,48", mode="workdays")
    assert res.rows[0].raw_cells.get(2, "") == "8-15,48"


def test_copy_first_employee_index_zero():
    """Регрессия: копирование графика с/на сотрудника index=0 работает."""
    res = res_for([
        mk_row(0, "Врач", "вр.пед.уч.", days={2: "8-15,48"}),
        mk_row(1, "Медсестра", "м/с"),
    ])
    copy_schedule(res, 0, 1)
    assert res.rows[1].raw_cells[2] == "8-15,48"


# --- autofill: только рабочие дни ------------------------------------------- #
def test_autofill_workdays():
    # ноябрь 2026: рабочие дни — 2,3,5,6,9,10,11,12,13,16,17,18,19,20,23,24,25,26,27,30
    res = res_for([mk_row(12, "Иванов И.И.", "зубной врач", week_norm=33)])
    warnings = autofill(res, 12, "8-15,48", mode="workdays")
    row = res.rows[0]
    assert row.raw_cells.get(1, "") == ""
    assert row.raw_cells.get(2, "") == "8-15,48"
    assert row.raw_cells.get(3, "") == "8-15,48"
    assert row.raw_cells.get(8, "") == ""
    assert round(row.total_hours, 1) == 156.0
    assert warnings == []


def test_autofill_does_not_overwrite():
    res = res_for([mk_row(12, "Петров П.П.", "зубной врач", week_norm=33,
                          days={2: "8-12"})])
    autofill(res, 12, "12,12-20", mode="workdays")
    assert res.rows[0].raw_cells[2] == "8-12"
    assert res.rows[0].raw_cells[3] == "12,12-20"


def test_autofill_status_code():
    res = res_for([mk_row(12, "Сидоров С.С.", "мед. регистр.", week_norm=40)])
    autofill(res, 12, "В", mode="empty")
    assert res.rows[0].parsed[1].kind == "status"
    assert len(res.rows[0].parsed) == 30


def test_autofill_errors():
    res = res_for([mk_row(12, "А", "м/с")])
    try:
        autofill(res, 12, "мусор", mode="empty")
        assert False, "плохая смена должна вызывать ValueError"
    except ValueError:
        pass
    try:
        autofill(res, 999, "8-15,48", mode="empty")
        assert False, "несуществующий сотрудник должен вызывать ValueError"
    except ValueError:
        pass


# --- copy_schedule ---------------------------------------------------------- #
def test_copy_schedule():
    res = res_for([
        mk_row(12, "Врач", "вр.пед.уч.", days={2: "8-15,48", 3: "8-15,48", 4: "В"}),
        mk_row(13, "Медсестра", "м/с"),
    ])
    copy_schedule(res, 12, 13)
    dst = res.rows[1]
    assert dst.raw_cells[2] == "8-15,48"
    assert dst.raw_cells[3] == "8-15,48"
    assert dst.raw_cells[4] == "В"
    assert round(dst.total_hours, 1) == 15.6


# --- generate_month --------------------------------------------------------- #
def test_generate_month_no_shifts():
    src = res_for([
        mk_row(12, "Врач", "вр.пед.уч.", week_norm=39, rate=0.5,
               days={2: "8-15,48", 3: "8-15,48"}),
    ])
    g = generate_month(src, 2026, 12, copy_shifts=False)
    assert (g.year, g.month) == (2026, 12)
    assert len(g.rows) == 1
    assert g.rows[0].name == "Врач"
    assert g.rows[0].rate == 0.5
    assert g.rows[0].week_norm == 39
    assert g.rows[0].total_hours == 0.0


def test_generate_month_copy_shifts():
    src = res_for([
        mk_row(12, "Врач", "вр.пед.уч.", week_norm=39, rate=0.5,
               days={2: "8-15,48", 3: "8-15,48"}),
    ])
    g2 = generate_month(src, 2026, 12, copy_shifts=True)
    filled = [d for d in range(1, g2.day_count + 1)
              if g2.rows[0].raw_cells.get(d, "") != ""]
    assert len(filled) > 0
    assert all(g2.rows[0].raw_cells[d] == "8-15,48" for d in filled)
