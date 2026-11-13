# -*- coding: utf-8 -*-
"""Тесты экспорта (CSV и табель Т-13)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.xls_importer import ImportResult, EmployeeRow
from app.services.time_parser import parse_cell
from app.services.exporter import export_csv, export_t13_html, tabel_code_for

fails = 0
def check(name, actual, expected):
    global fails
    ok = (actual == expected)
    if not ok:
        fails += 1
    print(("OK  " if ok else "FAIL") + " %-46s = %r (ожид. %r)" % (name, actual, expected))


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
row = mk_row(12, "Иванов И.И.", "зубной врач", week_norm=33,
             days={5: "8-15,48", 6: "В", 7: "ОТ", 8: "Б"})
check("код явки (день 5)", tabel_code_for(row, 5), ("Я", "7,8"))
check("код выходного (день 6)", tabel_code_for(row, 6), ("В", ""))
check("код отпуска (день 7)", tabel_code_for(row, 7), ("ОТ", ""))
check("код больничного (день 8)", tabel_code_for(row, 8), ("Б", ""))
check("пустой день", tabel_code_for(row, 9), ("", ""))

# --- export_csv ------------------------------------------------------------- #
res = res_for([
    mk_row(12, "Иванов И.И.", "зубной врач", week_norm=33,
           days={5: "8-15,48", 6: "12,12-20"}, norm_col=131.0),
])
csv_text = export_csv(res)
lines = csv_text.split("\n")
check("CSV: заголовок", lines[0].startswith("Ф.И.О.;Должность;Ставка;Недельная норма"), True)
check("CSV: строка данных", "Иванов И.И." in lines[1], True)
check("CSV: есть ставка", "1,00" in lines[1], True)
check("CSV: норма 131", "131" in lines[1], True)
check("CSV: есть день 5", "8-15,48" in lines[1], True)
check("CSV: заголовок дней", "День 1" in lines[0], True)

# --- export_t13_html -------------------------------------------------------- #
html = export_t13_html(res)
check("T13: заголовок Т-13", "Т-13" in html, True)
check("T13: месяц", "ноября" in html, True)
check("T13: имя", "Иванов И.И." in html, True)
check("T13: код явки", "Я" in html, True)
check("T13: часов 15,6", "15,6" in html, True)

print("\nИТОГО ПРОВАЛОВ: %d" % fails)
sys.exit(1 if fails else 0)
