# -*- coding: utf-8 -*-
"""Регрессионные тесты производственного календаря РФ.

Полные данные сверены с официальным календарём КонсультантПлюс:
  * 2024 — ПП РФ от 10.08.2023 N 1314
  * 2025 — ПП РФ от 04.10.2024 N 1335
  * 2026 — ПП РФ от 24.09.2025 N 1466
  * 2027 — ПП РФ от 17.09.2026 N 1187
  * 2020 — ПП РФ от 10.07.2019 N 875
  * 2021 — ПП РФ от 10.10.2020 N 1648
"""
import sys, os, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.calendar_rf import get_year_calendar, build_year_calendar, exact_years

out = []
fails = 0

def log(s=""):
    out.append(str(s))

def check(name, actual, expected):
    global fails
    if isinstance(expected, bool):
        ok = (actual == expected)
    elif isinstance(expected, (list, tuple)):
        ok = (list(actual) == list(expected))
    else:
        ok = abs(actual - expected) < 1e-9
    if not ok:
        fails += 1
    log(("OK " if ok else "FAIL ") + name + " = " + str(actual) + " (ожид. " + str(expected) + ")")

# =========================================================================== #
#  Полная помесячная проверка 2024–2027
# =========================================================================== #
FULL = {
    2024: dict(total_work=248, total_short=5, year_norm40=1979.0,
        months={1:(17,0),2:(20,1),3:(20,1),4:(21,0),5:(20,1),6:(19,1),
                7:(23,0),8:(22,0),9:(21,0),10:(23,0),11:(21,1),12:(21,0)},
        short_dates=[(2,22),(3,7),(5,8),(6,11),(11,2)]),
    2025: dict(total_work=247, total_short=4, year_norm40=1972.0,
        months={1:(17,0),2:(20,0),3:(21,1),4:(22,1),5:(18,0),6:(19,1),
                7:(23,0),8:(21,0),9:(22,0),10:(23,0),11:(19,1),12:(22,0)},
        short_dates=[(3,7),(4,30),(6,11),(11,1)]),
    2026: dict(total_work=247, total_short=4, year_norm40=1972.0,
        months={1:(15,0),2:(19,0),3:(21,0),4:(22,1),5:(19,1),6:(21,1),
                7:(23,0),8:(21,0),9:(22,0),10:(22,0),11:(20,1),12:(22,0)},
        short_dates=[(4,30),(5,8),(6,11),(11,3)]),
    2027: dict(total_work=247, total_short=4, year_norm40=1972.0,
        months={1:(15,0),2:(19,1),3:(22,0),4:(22,1),5:(19,0),6:(21,1),
                7:(22,0),8:(22,0),9:(22,0),10:(21,0),11:(20,1),12:(22,0)},
        short_dates=[(2,20),(4,30),(6,11),(11,3)]),
}

for year, spec in FULL.items():
    c = get_year_calendar(year)
    log("=" * 60)
    log("ГОД %d (need_verify=%s)" % (year, c.need_verify))
    tw = ts = 0
    for m in range(1, 13):
        w, s = c.month_stats(m)
        tw += w; ts += s
        ew, es = spec['months'][m]
        check("%d мес %02d раб.дней" % (year, m), w, ew)
        check("%d мес %02d предпраздн." % (year, m), s, es)
    check("%d раб.дней всего" % year, tw, spec['total_work'])
    check("%d предпраздн. всего" % year, ts, spec['total_short'])
    check("%d норма 40ч год" % year, c.norm_hours(40), spec['year_norm40'])
    short_dates = sorted((d.date.month, d.date.day) for d in c.days if d.is_shortened)
    check("%d список сокращённых" % year, short_dates, spec['short_dates'])

# =========================================================================== #
#  Итоги и ключевые даты 2020–2023
# =========================================================================== #
TOTALS = {
    2020: (248, 4, [(4,30),(5,8),(6,11),(11,3)]),
    2021: (247, 4, [(2,20),(4,30),(6,11),(11,3)]),
    2022: (247, 3, [(2,22),(3,5),(11,3)]),
    2023: (247, 3, [(2,22),(3,7),(11,3)]),
}
KEY_DATES = {
    # год: [(месяц, день, ожид_рабочий_день?), ...]
    2020: [(5,4,False),(5,5,False)],                    # перенос с 4/5 января
    2021: [(2,20,True),(2,22,False),(11,5,False),(12,31,False)],  # рабочая суббота + переносы
    2022: [(3,5,True),(3,7,False),(5,3,False),(5,10,False)],      # рабочая суббота + переносы
    2023: [(2,24,False),(5,8,False)],                  # переносы с 1/8 января
}
for year, (tw, tsh, sdates) in TOTALS.items():
    c = get_year_calendar(year)
    w, off, sh = c.year_stats()
    log("=" * 60)
    log("ГОД %d (need_verify=%s)" % (year, c.need_verify))
    check("%d раб.дней всего" % year, w, tw)
    check("%d предпраздн. всего" % year, sh, tsh)
    check("%d список сокращённых" % year,
          sorted((d.date.month, d.date.day) for d in c.days if d.is_shortened), sdates)
    for (m, d, is_work) in KEY_DATES[year]:
        check("%d %02d.%02d рабочий" % (year, d, m), c.is_work(m, d), is_work)

# =========================================================================== #
#  «Любой год»: 1990..2040 — календарь всегда строится, високосные корректны
# =========================================================================== #
log("=" * 60)
log("ПРОИЗВОЛЬНЫЕ ГОДЫ 1990..2040")
for year in range(1990, 2041):
    c = get_year_calendar(year)
    w, off, sh = c.year_stats()
    total = w + off
    exp_total = 366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365
    if total != exp_total:
        check("год %d всего дней" % year, total, exp_total)
    if year in exact_years():
        assert c.need_verify is False
    else:
        assert c.need_verify is True
check("точные годы = 2020..2027", exact_years(), list(range(2020, 2028)))

# Високосный 2024 = 366 дней, невисокосный 2026 = 365
check("2024 дней", sum(1 for _ in get_year_calendar(2024).days), 366)
check("2026 дней", sum(1 for _ in get_year_calendar(2026).days), 365)
check("2000 високосный (366)", sum(1 for _ in get_year_calendar(2000).days), 366)
check("1900 невисокосный (365)", sum(1 for _ in get_year_calendar(1900).days), 365)

log("")
log("ИТОГО ПРОВАЛОВ: %d" % fails)

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "calendar_result.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(out))
