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


# --------------------------------------------------------------------------- #
#  ОКУД 0504421 — табель учёта использования рабочего времени (бюджетные учр.)
# --------------------------------------------------------------------------- #
def export_okud_html(result: ImportResult, org: str = "ГУЗ «СГП № 16»",
                     dept: str = "") -> str:
    """Табель по форме ОКУД 0504421 (печатный HTML, бюджетный учёт).

    Каждый день — две строки в ячейке: сверху часы (для явки), снизу код отметки
    (Я/В/ОТ/Б/У). В конце — итоги: отработано дней/часов и неявки.
    """
    month_name = _RU_MONTHS_GEN[result.month - 1]

    # заголовок: две строки для дней (число сверху, «часы/код» снизу)
    day_cells_head = ""
    for d in range(1, result.day_count + 1):
        day_cells_head += "<th>%d</th>" % d
    sub_head = ""
    for d in range(1, result.day_count + 1):
        sub_head += "<th><span class='h'>ч</span><span class='c'>код</span></th>"

    rows_html = []
    for i, r in enumerate(result.rows, 1):
        present, absent, _, hours = _attendance_summary(r)
        cells = []
        for d in range(1, result.day_count + 1):
            code, hrs = tabel_code_for(r, d)
            if code == "Я":
                top, bottom = _html.escape(hrs), "Я"
                cls = ""
            elif code in ("В", "ОТ", "Б", "У"):
                top, bottom, cls = "", _html.escape(code), " off"
            else:
                top, bottom, cls = "", "", ""
            cells.append(
                '<td class="d%s"><span class="hrs">%s</span>'
                '<span class="code">%s</span></td>' % (cls, top, bottom))
        rows_html.append(
            "<tr><td class='c-num'>%d</td>"
            "<td class='c-name'>%s<br><i>%s</i></td>"
            "%s"
            "<td class='c-num'>%d</td>"
            "<td class='c-num'>%s</td>"
            "<td class='c-num'>%d</td>"
            "</tr>" % (i, _html.escape(r.name), _html.escape(r.position),
                       "".join(cells), present, _fmt(hours), absent))

    return """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>Табель ОКУД 0504421 %s %d</title>
<style>
body{font-family:"Times New Roman",serif;margin:20px;color:#000;}
table{border-collapse:collapse;width:100%%;}
th,td{border:1px solid #000;font-size:10px;text-align:center;vertical-align:middle;padding:1px 2px;}
.c-num{min-width:20px;}
.c-name{text-align:left;padding:3px 6px;min-width:160px;}
.c-name i{color:#444;font-size:9px;}
td.d span{display:block;min-height:9px;}
td.d .hrs{font-size:9px;}
td.d .code{font-weight:700;font-size:10px;}
td.d.off .code{color:#555;}
td.d .h,td.d .c{display:block;font-size:8px;color:#555;}
h1{font-size:15px;text-align:center;margin:0 0 4px;}
.meta{width:100%%;border:none;font-size:11px;margin-bottom:8px;}
.meta td{border:none;text-align:left;padding:1px 4px;}
.sub{text-align:center;font-size:11px;margin:4px 0 8px;color:#000;}
</style></head><body>
<h1>Табель учёта использования рабочего времени и расчёта заработной платы</h1>
<div class="sub">Код формы ОКУД 0504421 · за %s %d г.</div>
<table class="meta">
<tr><td>Учреждение:</td><td><b>%s</b></td><td>Структурное подразделение:</td><td><b>%s</b></td></tr>
</table>
<table>
<thead>
<tr><th rowspan="2">№</th><th rowspan="2">Фамилия, инициалы, должность</th>
%s
<th colspan="2">Отработано</th><th rowspan="2">Неявки (дней)</th></tr>
<tr>%s<th>дней</th><th>часов</th></tr>
</thead>
<tbody>%s</tbody>
</table>
</body></html>""" % (
        month_name, result.year, month_name, result.year,
        _html.escape(org), _html.escape(dept),
        day_cells_head, sub_head, "".join(rows_html))


# --------------------------------------------------------------------------- #
#  График на подпись (печатная форма с УТВЕРЖДАЮ / СОГЛАСОВАНО)
# --------------------------------------------------------------------------- #
def export_signoff_html(result: ImportResult, org: str = "ГУЗ «СГП № 16»",
                        head: str = "Главный врач ГУЗ «СГП № 16» Н.А. Глухова",
                        dept: str = "") -> str:
    """График работы для утверждения и подписи (печатный HTML).

    Содержит блоки «УТВЕРЖДАЮ» и «СОГЛАСОВАНО», таблицу смен по дням и колонку
    для подписи сотрудника.
    """
    month_name = _RU_MONTHS_GEN[result.month - 1]

    day_head = "".join("<th>%d</th>" % d for d in range(1, result.day_count + 1))
    rows_html = []
    for i, r in enumerate(result.rows, 1):
        cells = []
        for d in range(1, result.day_count + 1):
            raw = r.raw_cells.get(d, "")
            cells.append('<td class="d">%s</td>' % _html.escape(raw))
        rows_html.append(
            "<tr><td class='c-num'>%d</td>"
            "<td class='c-name'>%s<br><i>%s</i></td>"
            "%s<td class='c-sign'></td></tr>" % (
                i, _html.escape(r.name), _html.escape(r.position),
                "".join(cells)))

    return """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>График %s %d</title>
<style>
body{font-family:"Times New Roman",serif;margin:20px;color:#000;}
table{border-collapse:collapse;width:100%%;}
th,td{border:1px solid #000;font-size:10px;text-align:center;vertical-align:middle;padding:2px 3px;}
.c-num{min-width:20px;}
.c-name{text-align:left;padding:3px 6px;min-width:170px;}
.c-name i{color:#444;font-size:9px;}
td.d{font-size:10px;min-width:30px;}
.c-sign{min-width:46px;}
h1{font-size:16px;text-align:center;margin:6px 0 2px;}
.sub{text-align:center;font-size:12px;margin-bottom:12px;}
.approve{display:flex;justify-content:space-between;margin-bottom:10px;font-size:12px;}
.approve .box{width:45%%;}
.approve .line{margin-top:34px;border-top:1px solid #000;}
</style></head><body>
<h1>ГРАФИК РАБОТЫ</h1>
<div class="sub">%s · %s · на %s %d года</div>
<div class="approve">
<div class="box">УТВЕРЖДАЮ<br><b>%s</b><div class="line">подпись, дата</div></div>
<div class="box">СОГЛАСОВАНО<br><b>Председатель профсоюзного комитета</b><div class="line">подпись, дата</div></div>
</div>
<table>
<thead><tr><th>№</th><th>Ф.И.О., должность</th>%s<th>Подпись</th></tr></thead>
<tbody>%s</tbody>
</table>
</body></html>""" % (
        month_name, result.year,
        _html.escape(org), _html.escape(dept), month_name, result.year,
        _html.escape(head), day_head, "".join(rows_html))
