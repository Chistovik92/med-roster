# -*- coding: utf-8 -*-
"""Тесты валидатора (5 типов ошибок) на синтетических данных."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.xls_importer import ImportResult, EmployeeRow
from app.services.time_parser import parse_cell
from app.services.conflict_checker import (
    check_wrong_norm, check_overlaps, check_missing_shorten,
    check_duplicate_rows, check_hours_mismatch, check_unknown_position,
    check_all, WRONG_NORM, OVERLAP, MISSING_SHORTEN, DUPLICATE_ROW,
    HOURS_MISMATCH, UNKNOWN_POSITION, normalize_name,
)

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
    return ImportResult(source="synthetic", year=year, month=month,
                        day_count=day_count, rows=rows)


# --- normalize_name --------------------------------------------------------- #
check("normalize_name", normalize_name(" Афанасьева  И. Н. "), "афанасьева и.н.")

# --- тип 1: неверная норма в «Прим.» --------------------------------------- #
res = res_for([mk_row(12, "Медведева К.Д.", "вр.пед.уч.", week_norm=39,
                      rate=1.0, norm_col=159.0)])  # должно быть 155
c = check_wrong_norm(res)
check("тип1 найден", any(x.code == WRONG_NORM for x in c), True)
# корректная норма не должна флагаться
res2 = res_for([mk_row(12, "Симонова Н.А.", "вр.пед.уч.", week_norm=39,
                       rate=1.0, norm_col=155.0)])
check("тип1 корректная норма не флагуется", check_wrong_norm(res2), [])

# --- тип 2: накладка интервалов ставок ------------------------------------- #
res = res_for([
    mk_row(12, "Макарова Н.В.", "вр.пед.уч.", days={3: "8-15,48"}),
    mk_row(13, "Макарова Н.В.", "0,5 ед мс уч", days={3: "12,12-20"}),
])
c = check_overlaps(res)
check("тип2 найден", any(x.code == OVERLAP and x.day == 3 for x in c), True)
# без пересечения (8-12 и 13-20) не флагается
res = res_for([
    mk_row(12, "Прусова С.А.", "вр.пед.уч.", days={5: "8-12"}),
    mk_row(13, "Прусова С.А.", "0,5 ед мс уч", days={5: "13-20"}),
])
check("тип2 без накладки не флагуется", check_overlaps(res), [])

# --- тип 3: забытое сокращение предпраздничного дня ------------------------ #
# 3.11.2026 — предпраздничный; обычная смена 7,8 ч, в предпраздничный не сокращена
days = {5: "12,12-20", 6: "12,12-20", 9: "12,12-20", 10: "12,12-20"}
days[3] = "12,12-20"
res = res_for([mk_row(12, "Регистратор", "мед. регистр.", days=days, week_norm=40)])
c = check_missing_shorten(res)
check("тип3 найден", any(x.code == MISSING_SHORTEN and x.day == 3 for x in c), True)
# корректно сокращённая смена (6,8 ч) не флагается
days[3] = "12,12-19"
res = res_for([mk_row(12, "Регистратор", "мед. регистр.", days=days, week_norm=40)])
check("тип3 сокращённая смена не флагуется", check_missing_shorten(res), [])

# --- тип 4: дублирование строк --------------------------------------------- #
days = {5: "8-15,48", 6: "12,12-20"}
res = res_for([
    mk_row(12, "Блохин И.С.", "0,5 ед м/с", days=days),
    mk_row(13, "Блохин И.С.", "0,5 ед м/с", days=days),
])
c = check_duplicate_rows(res)
check("тип4 найден", any(x.code == DUPLICATE_ROW for x in c), True)

# --- тип 5: расхождение сумм часов ----------------------------------------- #
res = res_for([mk_row(12, "Иванов И.И.", "зубной врач", week_norm=33,
                      days={5: "8-15,48", 6: "12,12-20"}, sum_col=20.0)])  # факт 15.6
c = check_hours_mismatch(res)
check("тип5 найден", any(x.code == HOURS_MISMATCH for x in c), True)

# --- неизвестная должность -------------------------------------------------- #
res = res_for([mk_row(12, "Петров П.П.", "", week_norm=None)])
check("неизвестная должность", any(x.code == UNKNOWN_POSITION for x in check_unknown_position(res)), True)

# --- полный прогон не падает и собирает все типы --------------------------- #
big = res_for([
    mk_row(12, "Медведева К.Д.", "вр.пед.уч.", week_norm=39, norm_col=159.0),
    mk_row(13, "Макарова Н.В.", "вр.пед.уч.", days={3: "8-15,48"}),
    mk_row(14, "Макарова Н.В.", "0,5 ед мс уч", days={3: "12,12-20"}),
])
allc = check_all(big)
codes = {x.code for x in allc}
check("check_all находит тип1 и тип2", WRONG_NORM in codes and OVERLAP in codes, True)

print("\nИТОГО ПРОВАЛОВ: %d" % fails)
sys.exit(1 if fails else 0)
