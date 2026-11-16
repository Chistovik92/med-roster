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
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.calendar_rf import get_year_calendar, build_year_calendar, exact_years  # noqa: F401


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


def test_full_monthly_2024_2027():
    for year, spec in FULL.items():
        c = get_year_calendar(year)
        tw = ts = 0
        for m in range(1, 13):
            w, s = c.month_stats(m)
            tw += w
            ts += s
            ew, es = spec["months"][m]
            assert w == ew, "%d мес %02d раб.дней" % (year, m)
            assert s == es, "%d мес %02d предпраздн." % (year, m)
        assert tw == spec["total_work"], "%d раб.дней всего" % year
        assert ts == spec["total_short"], "%d предпраздн. всего" % year
        assert c.norm_hours(40) == spec["year_norm40"], "%d норма 40ч год" % year
        short_dates = sorted((d.date.month, d.date.day) for d in c.days if d.is_shortened)
        assert short_dates == spec["short_dates"], "%d список сокращённых" % year


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
    2022: [(3,5,True),(3,7,False),(5,3,False),(5,10,False)],    # рабочая суббота + переносы
    2023: [(2,24,False),(5,8,False)],                  # переносы с 1/8 января
}


def test_totals_2020_2023():
    for year, (tw, tsh, sdates) in TOTALS.items():
        c = get_year_calendar(year)
        w, off, sh = c.year_stats()
        assert w == tw, "%d раб.дней всего" % year
        assert sh == tsh, "%d предпраздн. всего" % year
        assert sorted((d.date.month, d.date.day) for d in c.days if d.is_shortened) == sdates
        for (m, d, is_work) in KEY_DATES[year]:
            assert c.is_work(m, d) == is_work, "%d %02d.%02d рабочий" % (year, d, m)


# =========================================================================== #
#  «Любой год»: 1990..2040 — календарь всегда строится, високосные корректны
# =========================================================================== #
def test_arbitrary_years_1990_2040():
    for year in range(1990, 2041):
        c = get_year_calendar(year)
        w, off, sh = c.year_stats()
        total = w + off
        exp_total = 366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365
        assert total == exp_total, "год %d всего дней" % year
        if year in exact_years():
            assert c.need_verify is False
        else:
            assert c.need_verify is True


def test_exact_years_range():
    assert exact_years() == list(range(2020, 2028))


def test_leap_years():
    # Високосный 2024 = 366 дней, невисокосный 2026 = 365
    assert sum(1 for _ in get_year_calendar(2024).days) == 366
    assert sum(1 for _ in get_year_calendar(2026).days) == 365
    assert sum(1 for _ in get_year_calendar(2000).days) == 366
    assert sum(1 for _ in get_year_calendar(1900).days) == 365
