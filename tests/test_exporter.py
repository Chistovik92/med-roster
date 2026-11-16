# -*- coding: utf-8 -*-
"""Тесты экспорта (CSV и табель Т-13)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.xls_importer import ImportResult, EmployeeRow
from app.services.time_parser import parse_cell
from app.services.exporter import (
    export_csv, export_t13_html, export_okud_html, export_signoff_html,
    tabel_code_for,
)


def mk_row(index, name, position, days=None, week_norm=39, rate=1.0,
           sum_col=None, norm_col=None):
    row = EmployeeRow(index=index, name=name, position=position,
                      rate=rate, week_norm=week_norm)
    if days:
        for d, val in days.items():
            row.raw_cells[d] = val
            row.parsed[d] = parse_cell(val)
    row.total_hours = sum(p.total_hours for p in row.parsed.values())
    row.sum_col = sum_col
    row.norm_col = norm_col
    return row


def res_for(rows, year=2026, month=11, day_count=30):
    return ImportResult(source="synthetic.xls", year=year, month=month,
                        day_count=day_count, rows=rows)


# --- tabel_code_for --------------------------------------------------------- #
def test_tabel_code_for():
    row = mk_row(12, "Иванов И.И.", "зубной врач", week_norm=33,
                 days={5: "8-15,48", 6: "В", 7: "ОТ", 8: "Б"})
    assert tabel_code_for(row, 5) == ("Я", "7,8")
    assert tabel_code_for(row, 6) == ("В", "")
    assert tabel_code_for(row, 7) == ("ОТ", "")
    assert tabel_code_for(row, 8) == ("Б", "")
    assert tabel_code_for(row, 9) == ("", "")


# --- export_csv ------------------------------------------------------------- #
def test_export_csv():
    res = res_for([
        mk_row(12, "Иванов И.И.", "зубной врач", week_norm=33,
               days={5: "8-15,48", 6: "12,12-20"}, norm_col=131.0),
    ])
    csv_text = export_csv(res)
    lines = csv_text.split("\n")
    assert lines[0].startswith("Ф.И.О.;Должность;Ставка;Недельная норма")
    assert "Иванов И.И." in lines[1]
    assert "1,00" in lines[1]
    assert "131" in lines[1]
    assert "8-15,48" in lines[1]
    assert "День 1" in lines[0]


# --- export_t13_html -------------------------------------------------------- #
def test_export_t13_html():
    res = res_for([mk_row(12, "Иванов И.И.", "зубной врач", week_norm=33,
                          days={5: "8-15,48", 6: "12,12-20"}, norm_col=131.0)])
    html = export_t13_html(res)
    assert "Т-13" in html
    assert "ноября" in html
    assert "Иванов И.И." in html
    assert "Я" in html
    assert "15,6" in html


# --- export_okud_html (ОКУД 0504421) --------------------------------------- #
def test_export_okud_html():
    res = res_for([mk_row(12, "Иванов И.И.", "зубной врач", week_norm=33,
                          days={5: "8-15,48", 6: "12,12-20"}, norm_col=131.0)])
    okud = export_okud_html(res)
    assert "0504421" in okud
    assert "ноября" in okud
    assert "Иванов И.И." in okud
    assert "Я" in okud
    assert "Отработано" in okud


# --- export_signoff_html (график на подпись) -------------------------------- #
def test_export_signoff_html():
    res = res_for([mk_row(12, "Иванов И.И.", "зубной врач", week_norm=33,
                          days={5: "8-15,48", 6: "12,12-20"}, norm_col=131.0)])
    sign = export_signoff_html(res)
    assert "УТВЕРЖДАЮ" in sign
    assert "СОГЛАСОВАНО" in sign
    assert "ГРАФИК РАБОТЫ" in sign
    assert "Иванов И.И." in sign
    assert "8-15,48" in sign
