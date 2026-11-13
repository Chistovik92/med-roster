# -*- coding: utf-8 -*-
"""
Экспорт графика: CSV (исправленный график) и табель учёта рабочего времени
(форма Т-13 / ОКУД 0504421) в виде печатного HTML.

Табель использует коды отметок (Постановление Госкомстата № 1, форма Т-13):
  Я — явка (работа), В — выходной, ОТ — ежегодный отпуск, Б — больничный,
  У — учебный отпуск. Для работы дополнительно указывается число часов.
"""
from __future__ import annotations

import csv
import io
import html as _html
from typing import List, Tuple

from app.services.xls_importer import ImportResult, EmployeeRow

# Канонический тип неявки -> код в табеле.
_TABEL_CODE = {"day_off": "В", "vacation": "ОТ", "sick": "Б", "study": "У"}

_RU_MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня",
                  "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def tabel_code_for(row: EmployeeRow, day: int) -> Tuple[str, str]:
    """Код отметки и число часов для ячейки табеля.

    Возвращает ``(код, часы)``: код — «Я»/«В»/«ОТ»/«Б»/«У»/«», часы — строка
    с количеством отработанных часов (для явки) или пустая.
    """
    pc = row.parsed.get(day)
    if pc is None:
        return "", ""
    if pc.kind == "status":
        return _TABEL_CODE.get(pc.status, ""), ""
    if pc.kind == "shift":
        return "Я", _fmt(pc.total_hours)
    if pc.kind == "invalid":
        return "?", ""
    return "", ""


def _fmt(hours: float) -> str:
    return ("%.1f" % hours).rstrip("0").rstrip(".").replace(".", ",")


def _attendance_summary(row: EmployeeRow) -> Tuple[int, int, int, float]:
    """(дней явок, дней неявок, рабочих дней, часов) — для итогов табеля."""
    present = 0
    absent = 0
    for pc in row.parsed.values():
        if pc.kind == "shift":
            present += 1
        elif pc.kind == "status":
            absent += 1
    return present, absent, present + absent, row.total_hours


# --------------------------------------------------------------------------- #
#  CSV — исправленный график
# --------------------------------------------------------------------------- #
def export_csv(result: ImportResult) -> str:
    """Выгрузить график в CSV (разделитель «;», совместимо с Excel)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    header = ["Ф.И.О.", "Должность", "Ставка", "Недельная норма"]
    header += ["День %d" % d for d in range(1, result.day_count + 1)]
    header += ["Часы (факт)", "Сумма (кол.32)", "Норма (Прим.)", "Отклонение"]
    w.writerow(header)
    for r in result.rows:
        row = [r.name, r.position,
               ("%.2f" % r.rate).replace(".", ","),
               (str(r.week_norm) if r.week_norm is not None else "")]
        row += [r.raw_cells.get(d, "") for d in range(1, result.day_count + 1)]
        dev = (round(r.total_hours - r.norm_col, 2)
               if r.norm_col is not None else "")
        row += [_fmt(r.total_hours),
                (_fmt(r.sum_col) if r.sum_col is not None else ""),
                (_fmt(r.norm_col) if r.norm_col is not None else ""),
                (("%+.1f" % dev).replace(".", ",") if dev != "" else "")]
        w.writerow(row)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
#  Табель Т-13 / ОКУД 0504421 (печатный HTML)
# --------------------------------------------------------------------------- #
def export_t13_html(result: ImportResult, org: str = "ГУЗ «СГП № 16»",
                    dept: str = "") -> str:
    """Сформировать табель учёта рабочего времени (форма Т-13) как HTML."""
    first = result.month
    month_name = _RU_MONTHS_GEN[first - 1]

    rows_html = []
    for i, r in enumerate(result.rows, 1):
        present, absent, _, hours = _attendance_summary(r)
        cells = []
        for d in range(1, result.day_count + 1):
            code, hrs = tabel_code_for(r, d)
            cells.append(
                '<td class="d%s"><span class="code">%s</span>'
                '<span class="hrs">%s</span></td>' % (
                    " off" if code in ("В", "ОТ", "Б", "У") else "",
                    _html.escape(code), _html.escape(hrs)))
        rows_html.append(
            "<tr>"
            "<td class='c-num'>%d</td>"
            "<td class='c-name'>%s<br><i>%s</i></td>"
            "%s"
            "<td class='c-num'>%d</td>"
            "<td class='c-num'>%s</td>"
            "</tr>" % (i,
                       _html.escape(r.name), _html.escape(r.position),
                       "".join(cells),
                       present, _fmt(hours)))

    half = (result.day_count + 1) // 2
    header1 = "<th></th><th></th>" + "".join(
        '<th colspan="%d">%d</th>' % (half if d == 1 else result.day_count - half, d)
        for d in (1, half + 1))
    header2 = "<th class='c-num'>№</th><th class='c-name'>Фамилия, инициалы, должность</th>"
    header2 += "".join("<th>%d</th>" % d for d in range(1, result.day_count + 1))
    header2 += "<th>Отработано дней</th><th>Отработано часов</th>"

    return """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>Табель %s %d</title>
<style>
body{font-family:"Times New Roman",serif;margin:24px;color:#000;}
table{border-collapse:collapse;width:100%%;}
th,td{border:1px solid #000;font-size:11px;text-align:center;vertical-align:middle;}
.c-num{min-width:22px;}
.c-name{text-align:left;padding:3px 6px;min-width:170px;}
.c-name i{color:#444;font-size:10px;}
td.d span{display:block;}
td.d .code{font-weight:700;}
td.d .hrs{font-size:9px;color:#333;min-height:10px;}
td.d.off .code{color:#555;}
h1{font-size:16px;text-align:center;margin:0 0 2px;}
.sub{text-align:center;font-size:11px;margin-bottom:10px;color:#333;}
</style></head><body>
<h1>Табель учёта рабочего времени и расчёта оплаты труда (форма Т-13)</h1>
<div class="sub">%s · %s · за %s %d г.</div>
<table>
<thead><tr>%s</tr><tr>%s</tr></thead>
<tbody>%s</tbody>
</table>
</body></html>""" % (
        month_name, result.year,
        _html.escape(org), _html.escape(dept), month_name, result.year,
        header1, header2, "".join(rows_html))
