# -*- coding: utf-8 -*-
"""
Производственный календарь РФ (пятидневная рабочая неделя) на произвольный год.

Нормативная база:
  * ст. 112 ТК РФ — нерабочие праздничные дни (состав зависит от года,
    см. holidays_for_year).
  * ст. 112 ч.2 ТК РФ — если праздник выпадает на субботу/воскресенье, выходной
    автоматически переносится на следующий рабочий день (кроме январских).
  * Постановления Правительства РФ — переносы выходных дней (таблица TRANSFERS),
    включая «рабочие субботы», которые авто-правило не покрывает.
  * ст. 95 ТК РФ — предпраздничный рабочий день сокращается на 1 час.
  * Приказ Минздравсоцразвития от 13.08.2009 № 588н — норма часов считается по
    расчётному графику пятидневной недели (недельная норма / 5 на каждый рабочий
    день, минус 1 час за каждый предпраздничный день).

Поддержка произвольных лет (вперёд и назад):
  * Годы с официально утверждёнными переносами (таблица TRANSFERS) считаются
    ТОЧНО. Текущая таблица покрывает 2020–2027.
  * Для прочих лет (будущие, а также прошлые вне таблицы) применяется
    автоматическое правило переноса и выставляется флаг ``need_verify`` — такой
    календарь пригоден для расчёта, но требует сверки с постановлением
    Правительства (для будущих лет его ещё нет; для прошлых — переносы
    «рабочих суббот» авто-правилом не воспроизводятся).
  * Состав праздников подбирается по году (ст. 112 менялась в 1992/2005/2012).
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Set, Tuple


# --------------------------------------------------------------------------- #
#  Нерабочие праздничные дни (ст. 112 ТК РФ).
#
#  Состав праздников исторически менялся, поэтому для каждого года берётся
#  свой список (см. holidays_for_year). Современный список (с 2012 года):
#    1–8 января (Новогодние каникулы + Рождество 7.01), 23 февраля, 8 марта,
#    1 мая, 9 мая, 12 июня, 4 ноября.
# --------------------------------------------------------------------------- #
FIXED_HOLIDAYS: List[Tuple[int, int]] = [
    (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 8),  # Новогодние каникулы
    (1, 7),    # Рождество Христово
    (2, 23),   # День защитника Отечества
    (3, 8),    # Международный женский день
    (5, 1),    # Праздник Весны и Труда
    (5, 9),    # День Победы
    (6, 12),   # День России
    (11, 4),   # День народного единства
]

# Праздники на 2005–2011 годы (новогодние каникулы 1–5 января; без 6–8 января).
_HOLIDAYS_2005_2011: List[Tuple[int, int]] = [
    (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 7),
    (2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4),
]

# Праздники на 1992–2004 годы (до реформы 2005 г.):
#  Новый год 1–2 января, 7 ноября (вместо 4 ноября), 12 декабря (с 1993),
#  23 февраля (с 2002), День Победы 9 мая, 1–2 мая.
_HOLIDAYS_1992_2004: List[Tuple[int, int]] = [
    (1, 1), (1, 2), (1, 7), (3, 8), (5, 1), (5, 2), (5, 9), (6, 12), (11, 7),
]

# Праздники до 1992 года (РСФСР/СССР) — приблизительно: Новый год 1–2 января,
# 7 ноября (День Октябрьской революции), 8 ноября, 5 декабря (День Конституции),
# 1–2 мая, 9 мая, 8 марта. (Для этих лет календарь помечается need_verify.)
_HOLIDAYS_BEFORE_1992: List[Tuple[int, int]] = [
    (1, 1), (1, 2), (3, 8), (5, 1), (5, 2), (5, 9), (11, 7), (11, 8), (12, 5),
]


def holidays_for_year(year: int) -> List[Tuple[int, int]]:
    """Список нерабочих праздничных дней (ст. 112 ТК РФ) для года.

    Учитывает изменения состава праздников:
      * с 2012 — новогодние каникулы 1–8 января;
      * 2005–2011 — 1–5 января (без 6–8 января);
      * 1992–2004 — 1–2 января, 7 ноября (вместо 4-го), 12 декабря (с 1993),
        23 февраля (с 2002);
      * до 1992 — советский перечень (приблизительно).
    """
    if year >= 2012:
        return FIXED_HOLIDAYS
    if year >= 2005:
        return _HOLIDAYS_2005_2011
    if year >= 1992:
        h = list(_HOLIDAYS_1992_2004)
        if year >= 1993:
            h.append((12, 12))
        if year >= 2002:
            h.append((2, 23))
        return h
    return _HOLIDAYS_BEFORE_1992


WEEKDAY_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _d(year: int, month: int, day: int) -> dt.date:
    return dt.date(year, month, day)


# --------------------------------------------------------------------------- #
#  Переносы выходных дней (Постановления Правительства РФ).
#  (src, dst): src — «источник» (праздничный или обычный выходной),
#               dst — куда переносится выходной (становится нерабочим).
# --------------------------------------------------------------------------- #
TRANSFERS: Dict[int, List[Tuple[dt.date, dt.date]]] = {
    2020: [
        (_d(2020, 1, 4), _d(2020, 5, 4)),    # ПП № 875 от 10.07.2019
        (_d(2020, 1, 5), _d(2020, 5, 5)),
    ],
    2021: [
        (_d(2021, 1, 2), _d(2021, 11, 5)),   # ПП № 1648 от 10.10.2020
        (_d(2021, 1, 3), _d(2021, 12, 31)),
        (_d(2021, 2, 20), _d(2021, 2, 22)),
    ],
    2022: [
        (_d(2022, 1, 1), _d(2022, 5, 3)),    # ПП № 1564 от 16.09.2021
        (_d(2022, 1, 2), _d(2022, 5, 10)),
        (_d(2022, 3, 5), _d(2022, 3, 7)),
    ],
    2023: [
        (_d(2023, 1, 1), _d(2023, 2, 24)),   # ПП № 1505 от 29.08.2022
        (_d(2023, 1, 8), _d(2023, 5, 8)),
    ],
    2024: [
        (_d(2024, 1, 6), _d(2024, 5, 10)),   # ПП № 1314 от 10.08.2023
        (_d(2024, 1, 7), _d(2024, 12, 31)),
        (_d(2024, 4, 27), _d(2024, 4, 29)),
        (_d(2024, 11, 2), _d(2024, 4, 30)),
        (_d(2024, 12, 28), _d(2024, 12, 30)),
    ],
    2025: [
        (_d(2025, 1, 4), _d(2025, 5, 2)),    # ПП № 1335 от 04.10.2024
        (_d(2025, 1, 5), _d(2025, 12, 31)),
        (_d(2025, 2, 23), _d(2025, 5, 8)),
        (_d(2025, 3, 8), _d(2025, 6, 13)),
        (_d(2025, 11, 1), _d(2025, 11, 3)),
    ],
    2026: [
        (_d(2026, 1, 3), _d(2026, 1, 9)),    # ПП № 1466 от 24.09.2025
        (_d(2026, 1, 4), _d(2026, 12, 31)),
    ],
    2027: [
        (_d(2027, 1, 2), _d(2027, 11, 5)),   # ПП № 1187 от 17.09.2026
        (_d(2027, 1, 3), _d(2027, 12, 31)),
        (_d(2027, 2, 20), _d(2027, 2, 22)),
    ],
}


class DayInfo(object):
    """Информация об одном календарном дне."""

    __slots__ = ("date", "weekday", "is_work", "is_shortened", "is_holiday")

    def __init__(self, date, weekday, is_work, is_shortened, is_holiday):
        self.date = date
        self.weekday = weekday
        self.is_work = is_work
        self.is_shortened = is_shortened
        self.is_holiday = is_holiday


class YearCalendar(object):
    """Производственный календарь на год (список дней + сводки)."""

    def __init__(self, year, days, need_verify):
        self.year = year
        self.days = days            # List[DayInfo]
        self.need_verify = need_verify

    # -- доступ по дате --------------------------------------------------- #
    def day(self, month, day):
        for d in self.days:
            if d.date.month == month and d.date.day == day:
                return d
        return None

    def is_work(self, month, day):
        d = self.day(month, day)
        return bool(d and d.is_work)

    # -- сводки ----------------------------------------------------------- #
    def month_stats(self, month):
        """(рабочих_дней, предпраздничных_дней) в месяце."""
        work = 0
        short = 0
        for d in self.days:
            if d.date.month == month:
                if d.is_work:
                    work += 1
                    if d.is_shortened:
                        short += 1
        return work, short

    def year_stats(self):
        work = sum(1 for d in self.days if d.is_work)
        off = sum(1 for d in self.days if not d.is_work)
        short = sum(1 for d in self.days if d.is_shortened)
        return work, off, short

    # -- нормы часов ------------------------------------------------------ #
    def norm_hours(self, weekly_hours, month=None, rate=1.0):
        """Норма часов по Приказу № 588н.

        weekly_hours — недельная норма (40, 39, 36, 33, 30, 24 и т.д.).
        month        — если указан, норма только за месяц (иначе за год).
        rate         — доля ставки (1.0, 0.5, 0.25 ...).
        """
        if month is None:
            work, _, short = self.year_stats()
        else:
            work, short = self.month_stats(month)
        daily = float(weekly_hours) / 5.0
        return round((daily * work - short * 1.0) * rate, 2)


# --------------------------------------------------------------------------- #
#  Построение календаря
# --------------------------------------------------------------------------- #
def build_year_calendar(year: int) -> YearCalendar:
    holidays = set(_d(year, m, d) for (m, d) in holidays_for_year(year))

    all_dates = []
    cur = dt.date(year, 1, 1)
    while cur.year == year:
        all_dates.append(cur)
        cur += dt.timedelta(days=1)

    day_off = set()          # нерабочие дни (выходные + праздники + переносы)
    work_saturdays = set()   # выходные, ставшие рабочими («рабочие субботы»)

    # 1) обычные выходные (сб/вс)
    for d in all_dates:
        if d.weekday() >= 5:
            day_off.add(d)

    # 2) праздники
    for d in all_dates:
        if d in holidays:
            day_off.add(d)

    transfers = TRANSFERS.get(year, [])
    explicit_src = {src for src, _ in transfers}

    # 3) авто-перенос: не январский праздник на выходном -> ближайший рабочий день
    #    (январские праздники переносятся только постановлением Правительства)
    for d in all_dates:
        if d in holidays and d.month != 1 and d.weekday() >= 5:
            if d in explicit_src:
                continue  # есть явный перенос — авто-правило не применяем
            nxt = d + dt.timedelta(days=1)
            while nxt in day_off and nxt.year == year:
                nxt += dt.timedelta(days=1)
            if nxt.year == year:
                day_off.add(nxt)

    # 4) явные переносы
    for src, dst in transfers:
        day_off.add(dst)
        if src in holidays:
            pass  # источник — праздник, остаётся нерабочим
        else:
            day_off.discard(src)  # «рабочая суббота»
            work_saturdays.add(src)

    # 5) предпраздничные дни (сокращённые на 1 час)
    shortened = set()
    for d in all_dates:
        if d in holidays:
            prev = d - dt.timedelta(days=1)
            if prev.year == year and prev not in day_off:
                shortened.add(prev)

    # 5а) «рабочая суббота», унаследовавшая сокращение перенесённого дня.
    #     По Приказу 588н: при переносе выходного дня на рабочий день
    #     продолжительность работы в «бывший выходной» (src) должна
    #     соответствовать продолжительности рабочего дня, куда перенесён
    #     выходной (dst). Если dst — канун праздника (был бы сокращён),
    #     то src тоже становится сокращённым. Пример: 2027 — 20.02→22.02,
    #     22.02 — канун 23.02 ⇒ 20.02 сокращённый рабочий день.
    for src, dst in transfers:
        if src in holidays:
            continue  # источник — праздник, «рабочей субботы» нет
        if dst + dt.timedelta(days=1) in holidays:
            shortened.add(src)

    # 6) сборка
    days = [
        DayInfo(
            date=d,
            weekday=d.weekday(),
            is_work=(d not in day_off),
            is_shortened=(d in shortened),
            is_holiday=(d in holidays),
        )
        for d in all_dates
    ]

    need_verify = year not in TRANSFERS
    return YearCalendar(year, days, need_verify)


def exact_years() -> List[int]:
    """Годы с официально утверждёнными переносами (календарь точен без сверки)."""
    return sorted(TRANSFERS.keys())


_CACHE: Dict[int, YearCalendar] = {}


def get_year_calendar(year: int) -> YearCalendar:
    """Кэширующий доступ к календарю года."""
    if year not in _CACHE:
        _CACHE[year] = build_year_calendar(year)
    return _CACHE[year]


def norm_hours(year: int, month: int, weekly_hours: float, rate: float = 1.0) -> float:
    """Короткий помощник: норма часов за конкретный месяц."""
    return get_year_calendar(year).norm_hours(weekly_hours, month=month, rate=rate)
