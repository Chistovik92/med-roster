# -*- coding: utf-8 -*-
"""
Расчёт нормы рабочего времени (Приказ Минздравсоцразвития от 13.08.2009 № 588н).

Формула месячной нормы:
    M_баз = (W_нед / 5 × N_раб − H_предпр) × rate
    M_инд = M_баз − (W_нед / 5 × N_неявок_раб × rate)
    Δ     = Σ H_факт − M_инд

где:
  * W_нед      — недельная норма (30/33/36/39/40 ч);
  * N_раб      — число рабочих дней в месяце (по производственному календарю);
  * H_предпр   — число предпраздничных (сокращённых) дней × 1 час;
  * rate       — доля ставки (1.0 / 0.75 / 0.5 / 0.25);
  * N_неявок_раб — число дней неявок, приходящихся на рабочие дни.

Норма считается по расчётному графику ПЯТИДНЕВНОЙ недели независимо от
фактического сменного графика (п. 1 Порядка 588н): недельная норма делится на 5
и умножается на число рабочих дней, минус 1 час за каждый предпраздничный день.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from app.core.calendar_rf import get_year_calendar
from app.core.constants import DEFAULT_WEEK_NORM, HOURS_ROUND


def daily_hours(week_norm: float) -> float:
    """Часовая норма одного рабочего дня при пятидневной неделе (W_нед / 5)."""
    return week_norm / 5.0


def monthly_base_norm(week_norm: float, year: int, month: int,
                      rate: float = 1.0) -> float:
    """Базовая месячная норма (без вычета неявок), в часах.

    M_баз = (W_нед / 5 × N_раб − H_предпр) × rate
    """
    cal = get_year_calendar(year)
    work_days, short_days = cal.month_stats(month)
    return (daily_hours(week_norm) * work_days - short_days) * rate


def monthly_individual_norm(week_norm: float, year: int, month: int,
                            rate: float = 1.0,
                            absence_work_days: Sequence[int] = ()) -> float:
    """Индивидуальная месячная норма с учётом неявок, в часах.

    ``absence_work_days`` — номера дней месяца (1-based), в которые сотрудник
    отсутствовал и которые являются рабочими днями календаря. Предпраздничный
    день отсутствия вычитается как сокращённый (минус 1 час).

    M_инд = M_баз − (W_нед / 5 × N_неявок_раб × rate)
    """
    cal = get_year_calendar(year)
    base = monthly_base_norm(week_norm, year, month, rate)
    day_hours = daily_hours(week_norm)
    absent = 0.0
    for day in absence_work_days:
        d = cal.day(month, day)
        if d is not None and d.is_work:
            h = day_hours - (1.0 if d.is_shortened else 0.0)
            absent += h * rate
    return base - absent


def deviation(actual_hours: float, individual_norm: float) -> float:
    """Отклонение фактических часов от индивидуальной нормы (Δ = ΣH_факт − M_инд)."""
    return actual_hours - individual_norm


def year_norm(week_norm: float, year: int) -> float:
    """Годовая норма часов для недельной нормы (по календарю года)."""
    cal = get_year_calendar(year)
    return cal.norm_hours(week_norm)


def round_hours(hours: float, ndigits: int = HOURS_ROUND) -> float:
    """Округлить часы до заданного числа знаков (по умолчанию 1)."""
    return round(hours + 1e-9, ndigits)
