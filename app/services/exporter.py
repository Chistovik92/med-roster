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
from typing import List, Optional, Tuple

from app import __version__
from app.core.constants import DEFAULT_ORG
from app.services.norm_calculator import monthly_base_norm
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
#  XLS — исправленный график в исходном табличном формате
# --------------------------------------------------------------------------- #
def export_xls(result: ImportResult, org: str = DEFAULT_ORG,
               dept: str = "") -> bytes:
    """Сформировать бинарный ``.xls`` с исправленными ячейками и итогами.

    Дни начинаются с колонки C; сумма/дополнительная колонка/норма следуют
    сразу после последнего дня. Поэтому файл корректен и для 30-, и для
    31-дневного месяца и может быть снова импортирован в программу.
    """
    import xlwt

    book = xlwt.Workbook(encoding="utf-8")
    sheet = book.add_sheet("Лист1")
    sum_col = result.day_count + 2
    extra_col = sum_col + 1
    norm_col = sum_col + 2

    border = "borders: left thin, right thin, top thin, bottom thin;"
    center = xlwt.easyxf(border + "align: horiz center, vert center;")
    left = xlwt.easyxf(border + "align: horiz left, vert center;")
    header = xlwt.easyxf(border + "font: bold true;align: horiz center, vert center;")
    title = xlwt.easyxf("font: bold true, height 280;align: horiz center;")
    meta = xlwt.easyxf("font: bold true;align: horiz left;")

    sheet.col(0).width = 7000
    sheet.col(1).width = 6500
    for d in range(1, result.day_count + 1):
        sheet.col(d + 1).width = 2600
    for c in (sum_col, extra_col, norm_col):
        sheet.col(c).width = 2500

    sheet.write_merge(0, 0, 0, norm_col,
                      "%s%s" % (org, (" · " + dept) if dept else ""), meta)
    sheet.write_merge(1, 1, 0, norm_col, "ГРАФИК РАБОТЫ", title)
    sheet.write_merge(2, 2, 0, norm_col,
                      "на %s %d года" % (_RU_MONTHS_GEN[result.month - 1], result.year), meta)
    sheet.write(11, 0, "Ф.И.О.", header)
    sheet.write(11, 1, "Должность", header)
    for d in range(1, result.day_count + 1):
        sheet.write(11, d + 1, d, header)
    sheet.write(11, sum_col, "Сумма", header)
    sheet.write(11, extra_col, "", header)
    sheet.write(11, norm_col, "Прим.", header)

    for i, row in enumerate(result.rows, 12):
        sheet.write(i, 0, row.name, left)
        position = row.position
        rate_label = ("%.2f" % row.rate).replace(".", ",").rstrip("0").rstrip(",")
        if row.rate != 1.0 and rate_label not in position.replace(".", ","):
            position = (position + " " if position else "") + (rate_label + " ед")
        sheet.write(i, 1, position, left)
        for d in range(1, result.day_count + 1):
            sheet.write(i, d + 1, row.raw_cells.get(d, ""), center)
        sheet.write(i, sum_col, round(row.total_hours, 1), center)
        sheet.write(i, extra_col, row.extra_col or "", center)
        norm = row.norm_col
        if norm is None and row.week_norm is not None:
            norm = monthly_base_norm(row.week_norm, result.year, result.month, row.rate)
        if norm is not None:
            sheet.write(i, norm_col, round(norm, 1), center)
        else:
            sheet.write(i, norm_col, "", center)

    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
#  Табель Т-13 / ОКУД 0504421 (печатный HTML)
# --------------------------------------------------------------------------- #
def export_t13_html(result: ImportResult, org: str = DEFAULT_ORG,
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
def export_okud_html(result: ImportResult, org: str = DEFAULT_ORG,
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
def export_signoff_html(result: ImportResult, org: str = DEFAULT_ORG,
                        head: Optional[str] = None, dept: str = "") -> str:
    """График работы для утверждения и подписи (печатный HTML).

    Содержит блоки «УТВЕРЖДАЮ» и «СОГЛАСОВАНО», таблицу смен по дням и колонку
    для подписи сотрудника. Строка «УТВЕРЖДАЮ» по умолчанию выводит
    «Главный врач <учреждение>» (название берётся из ``org``).
    """
    if head is None:
        head = "Главный врач %s" % org
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



# --------------------------------------------------------------------------- #
#  Подписанный пакет экспорта (ZIP + манифест + HMAC-SHA256).
#
#  Все пять форматов выгрузки собираются в один архив; рядом кладётся
#  manifest.json с контрольными суммами каждого файла и подписью манифеста
#  (manifest.sig). Получатель может убедиться, что файлы не изменялись после
#  выгрузки и не подделаны (см. app/core/signing.py).
# --------------------------------------------------------------------------- #
def export_signed_zip(result: ImportResult, org: str = DEFAULT_ORG,
                      dept: str = "", signer: str = "") -> bytes:
    """Собрать подписанный ZIP-пакет всех форматов экспорта (байты)."""
    import io as _io
    import json as _json
    import time as _time
    import zipfile as _zipfile

    from app.core import signing

    period = "%d-%02d" % (result.year, result.month)
    files = [
        ("graph_%s.csv" % period,
         export_csv(result).encode("utf-8")),
        ("graph_%s.xls" % period,
         export_xls(result, org=org, dept=dept)),
        ("tabel_T13_%s.html" % period,
         export_t13_html(result, org=org, dept=dept).encode("utf-8")),
        ("tabel_OKUD0504421_%s.html" % period,
         export_okud_html(result, org=org, dept=dept).encode("utf-8")),
        ("graph_podpis_%s.html" % period,
         export_signoff_html(result, org=org, dept=dept).encode("utf-8")),
    ]

    manifest_files = []
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED) as zf:
        for name, data in files:
            sig = signing.sign_bytes(data)
            zf.writestr(name, data)
            manifest_files.append({
                "name": name,
                "size": len(data),
                "sha256": sig["sha256"],
                "hmac_sha256": sig["hmac_sha256"],
            })
        manifest = {
            "app": "med-roster",
            "version": __version__,
            "generated_at": _time.strftime("%Y-%m-%dT%H:%M:%S"),
            "year": result.year,
            "month": result.month,
            "org": org,
            "department": dept,
            "signer": (signer or "").strip(),
            "algorithm": "HMAC-SHA256",
            "files": manifest_files,
        }
        manifest_bytes = _json.dumps(
            manifest, ensure_ascii=False, indent=2).encode("utf-8")
        zf.writestr("manifest.json", manifest_bytes)
        manifest_sig = signing.sign_bytes(manifest_bytes)
        zf.writestr("manifest.sig", manifest_sig["hmac_sha256"])

    return buf.getvalue()


def verify_signed_zip(zip_bytes: bytes) -> dict:
    """Проверить подписанный пакет: контрольные суммы и подпись манифеста.

    Возвращает {"ok": bool, "errors": [...], "files": [...]}. Проверяются:
    целостность каждого файла (sha256), подпись каждого файла (hmac) и
    подпись манифеста (manifest.sig). Используется эндпоинтом /export/verify
    и доступно МИС для самопроверки полученного пакета.
    """
    import io as _io
    import json as _json
    import zipfile as _zipfile

    from app.core import signing

    errors = []
    out_files = []
    with _zipfile.ZipFile(_io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if "manifest.json" not in names:
            return {"ok": False,
                    "errors": ["в пакете нет manifest.json"], "files": []}
        manifest_bytes = zf.read("manifest.json")
        manifest = _json.loads(manifest_bytes.decode("utf-8"))
        manifest_sig = ""
        if "manifest.sig" in names:
            manifest_sig = zf.read("manifest.sig").decode("utf-8").strip()
        else:
            errors.append("в пакете нет manifest.sig")
        if manifest_sig and not signing.verify_bytes(manifest_bytes, manifest_sig):
            errors.append("подпись манифеста не сошлась (данные изменены?)")

        for f in manifest.get("files", []):
            name = f.get("name", "")
            if name not in names:
                errors.append("в пакете нет файла: %s" % name)
                continue
            data = zf.read(name)
            sig = signing.sign_bytes(data)
            file_ok = (sig["sha256"] == f.get("sha256")
                       and sig["hmac_sha256"] == f.get("hmac_sha256"))
            if not file_ok:
                errors.append("контрольная сумма или подпись не сошлись: %s" % name)
            out_files.append({"name": name, "size": len(data), "ok": file_ok})

    return {"ok": not errors, "errors": errors, "files": out_files,
            "signer": manifest.get("signer", ""),
            "generated_at": manifest.get("generated_at", "")}
