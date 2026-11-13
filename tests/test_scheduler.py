# -*- coding: utf-8 -*-
"""Тесты планирования (автосмены, копирование графика)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.xls_importer import ImportResult, EmployeeRow
from app.services.time_parser import parse_cell
from app.services.scheduler import autofill, copy_schedule

fails = 0
def check(name, actual, expected):
    global fails
    ok = (actual == expected)
    if not ok:
        fails += 1
    print(("OK  " if ok else "FAIL") + " %-48s = %r (ожид. %r)" % (name, actual, expected))


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


# --- autofill: только рабочие дни ------------------------------------------- #
# ноябрь 2026: рабочие дни — 2,3,5,6,9,10,11,12,13,16,17,18,19,20,23,24,25,26,27,30
res = res_for([mk_row(12, "Иванов И.И.", "зубной врач", week_norm=33)])
warnings = autofill(res, 12, "8-15,48", mode="workdays")
row = res.rows[0]
check("autofill: день 1 (вс) пуст", row.raw_cells.get(1, ""), "")
check("autofill: день 2 (рабочий) заполнен", row.raw_cells.get(2, ""), "8-15,48")
check("autofill: день 3 (предпраздн.) заполнен", row.raw_cells.get(3, ""), "8-15,48")
check("autofill: день 8 (вс) пуст", row.raw_cells.get(8, ""), "")
# ноябрь 2026: 20 рабочих дней, все по 7,8 ч
check("autofill: часов 20x7,8", round(row.total_hours, 1), 156.0)
check("autofill: нет предупреждений", warnings, [])

# заполненные не перезаписываются
res2 = res_for([mk_row(12, "Петров П.П.", "зубной врач", week_norm=33,
                       days={2: "8-12"})])
autofill(res2, 12, "12,12-20", mode="workdays")
check("autofill: заполненный день не трогается", res2.rows[0].raw_cells[2], "8-12")
check("autofill: остальные рабочие заполнены", res2.rows[0].raw_cells[3], "12,12-20")

# --- autofill: код статуса -------------------------------------------------- #
res3 = res_for([mk_row(12, "Сидоров С.С.", "мед. регистр.", week_norm=40)])
autofill(res3, 12, "В", mode="empty")
check("autofill status: день 1 = В", res3.rows[0].parsed[1].kind, "status")
check("autofill status: все 30 дней заполнены", len(res3.rows[0].parsed), 30)

# --- autofill: ошибки ------------------------------------------------------- #
res4 = res_for([mk_row(12, "А", "м/с")])
try:
    autofill(res4, 12, "мусор", mode="empty")
    check("autofill: плохая смена -> ошибка", False, True)
except ValueError:
    check("autofill: плохая смена -> ошибка", True, True)
try:
    autofill(res4, 999, "8-15,48", mode="empty")
    check("autofill: несуществующий сотрудник -> ошибка", False, True)
except ValueError:
    check("autofill: несуществующий сотрудник -> ошибка", True, True)

# --- copy_schedule ---------------------------------------------------------- #
res5 = res_for([
    mk_row(12, "Врач", "вр.пед.уч.", days={2: "8-15,48", 3: "8-15,48", 4: "В"}),
    mk_row(13, "Медсестра", "м/с"),
])
copy_schedule(res5, 12, 13)
dst = res5.rows[1]
check("copy: день 2 скопирован", dst.raw_cells[2], "8-15,48")
check("copy: день 3 скопирован", dst.raw_cells[3], "8-15,48")
check("copy: код В скопирован", dst.raw_cells[4], "В")
check("copy: часов совпадает", round(dst.total_hours, 1), 15.6)

print("\nИТОГО ПРОВАЛОВ: %d" % fails)
sys.exit(1 if fails else 0)
