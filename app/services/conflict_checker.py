# -*- coding: utf-8 -*-
"""
Валидатор графика — воспроизводит 5 типов ошибок, найденных в реальных файлах.

Типы ошибок (см. AGENTS.md, раздел 7):
  1. «Неверная норма в колонке Прим.» — c34 («Прим.») не совпадает с месячной
     нормой, вычисленной по недельной норме должности (588н) и ставке.
  2. «Накладки времени ставок» — у одного человека несколько строк (основная +
     0,5/0,75 ставки), и их рабочие интервалы в один день пересекаются.
  3. «Забытое сокращение предпраздничного дня» — в предпраздничный день (ст. 95)
     смена не сокращена на 1 час относительно обычной.
  4. «Дублирование строк» — две строки одного человека с одинаковым содержимым.
  5. «Расхождения сумм часов» — фактическая сумма часов не совпадает с колонкой 32
     (сумма) и/или отклоняется от нормы «Прим.».
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.core.calendar_rf import get_year_calendar
from app.services.norm_calculator import monthly_base_norm
from app.services.xls_importer import ImportResult, EmployeeRow

# Коды типов ошибок.
WRONG_NORM = "wrong_norm"
OVERLAP = "overlap"
MISSING_SHORTEN = "missing_shorten"
DUPLICATE_ROW = "duplicate_row"
HOURS_MISMATCH = "hours_mismatch"
UNKNOWN_POSITION = "unknown_position"


@dataclass
class Conflict:
    """Одна найденная ошибка/предупреждение."""
    code: str
    severity: str          # 'error' | 'warning'
    message: str
    employee: Optional[str] = None
    day: Optional[int] = None
    details: Optional[str] = None

    def __str__(self):
        loc = []
        if self.employee:
            loc.append(self.employee)
        if self.day:
            loc.append("день %d" % self.day)
        prefix = " | ".join(loc)
        return "[%s] %s%s: %s" % (self.severity.upper(),
                                  (prefix + " — ") if prefix else "",
                                  self.code, self.message)


def normalize_name(name: str) -> str:
    """Нормализовать ФИО для сопоставления (регистр, пробелы, точки у инициалов)."""
    s = (name or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*\.\s*", ".", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _group_by_name(rows: List[EmployeeRow]) -> Dict[str, List[EmployeeRow]]:
    groups: Dict[str, List[EmployeeRow]] = {}
    for r in rows:
        groups.setdefault(normalize_name(r.name), []).append(r)
    return groups


# --------------------------------------------------------------------------- #
#  1. Неверная норма в «Прим.» (c34)
# --------------------------------------------------------------------------- #
def check_wrong_norm(result: ImportResult, tol: float = 1.0) -> List[Conflict]:
    out = []
    for r in result.rows:
        if r.week_norm is None or r.norm_col is None:
            continue
        expected = monthly_base_norm(r.week_norm, result.year, result.month, r.rate)
        if abs(expected - r.norm_col) > tol:
            out.append(Conflict(
                code=WRONG_NORM, severity="error", employee=r.name,
                message="норма в «Прим.» = %g, ожидается %g (нед. %d ч × %.2f ставки)"
                        % (r.norm_col, expected, r.week_norm, r.rate),
                details="строка %d, должность %r" % (r.index + 1, r.position),
            ))
    return out


# --------------------------------------------------------------------------- #
#  4. Дублирование строк
# --------------------------------------------------------------------------- #
def check_duplicate_rows(result: ImportResult) -> List[Conflict]:
    out = []
    for name, rows in _group_by_name(result.rows).items():
        n = len(rows)
        for i in range(n):
            for j in range(i + 1, n):
                a, b = rows[i], rows[j]
                if a.position == b.position and a.raw_cells == b.raw_cells:
                    out.append(Conflict(
                        code=DUPLICATE_ROW, severity="error",
                        employee=a.name or name,
                        message="две одинаковые строки (строки %d и %d): %r"
                                % (a.index + 1, b.index + 1, a.position),
                    ))
    return out


# --------------------------------------------------------------------------- #
#  2. Накладки времени ставок (пересечение интервалов одного человека)
# --------------------------------------------------------------------------- #
def _overlap(a, b) -> bool:
    return a.start < b.end and b.start < a.end


def check_overlaps(result: ImportResult) -> List[Conflict]:
    out = []
    for name, rows in _group_by_name(result.rows).items():
        if len(rows) < 2:
            continue
        # собираем интервалы по дням
        for day in range(1, result.day_count + 1):
            intervals = []
            owners = []
            for r in rows:
                pc = r.parsed.get(day)
                if pc is not None and pc.kind == "shift":
                    for iv in pc.intervals:
                        intervals.append(iv)
                        owners.append(r)
            for i in range(len(intervals)):
                for j in range(i + 1, len(intervals)):
                    if _overlap(intervals[i], intervals[j]):
                        out.append(Conflict(
                            code=OVERLAP, severity="error",
                            employee=name, day=day,
                            message="пересечение интервалов ставок "
                                    "(строки %d и %d)" % (owners[i].index + 1,
                                                          owners[j].index + 1),
                        ))
    return out


# --------------------------------------------------------------------------- #
#  3. Забытое сокращение предпраздничного дня
# --------------------------------------------------------------------------- #
def check_missing_shorten(result: ImportResult, delta: float = 0.2) -> List[Conflict]:
    """Эвристика: в предпраздничный день смена должна быть на ~1 ч короче обычной.

    Обычная длительность смены определяется как модальная по месяцу. Если в
    предпраздничный день длительность равна обычной (не сокращена) — предупреждение.
    """
    out = []
    cal = get_year_calendar(result.year)
    for r in result.rows:
        durations = [round(pc.total_hours, 1) for pc in r.parsed.values()
                     if pc.kind == "shift"]
        if not durations:
            continue
        typical = Counter(durations).most_common(1)[0][0]
        if typical <= 0:
            continue
        for day in range(1, result.day_count + 1):
            d = cal.day(result.month, day)
            if d is None or not d.is_shortened:
                continue
            pc = r.parsed.get(day)
            if pc is None or pc.kind != "shift":
                continue
            dur = round(pc.total_hours, 1)
            # не сокращена на ~1 ч от обычной
            if abs(dur - typical) < delta:
                out.append(Conflict(
                    code=MISSING_SHORTEN, severity="warning",
                    employee=r.name, day=day,
                    message="предпраздничный день не сокращён: смена %.1f ч "
                            "(обычная %.1f ч)" % (dur, typical),
                ))
    return out


# --------------------------------------------------------------------------- #
#  5. Расхождения сумм часов
# --------------------------------------------------------------------------- #
def check_hours_mismatch(result: ImportResult, sum_tol: float = 0.2,
                         norm_tol: float = 0.6) -> List[Conflict]:
    out = []
    for r in result.rows:
        total = round(r.total_hours, 2)
        if r.sum_col is not None and abs(total - r.sum_col) > sum_tol:
            out.append(Conflict(
                code=HOURS_MISMATCH, severity="error", employee=r.name,
                message="фактическая сумма %.1f ч ≠ колонка 32 (%.1f ч)"
                        % (total, r.sum_col),
            ))
        if r.norm_col is not None and abs(total - r.norm_col) > norm_tol:
            out.append(Conflict(
                code=HOURS_MISMATCH, severity="warning", employee=r.name,
                message="отклонение от нормы: %.1f ч против %.1f ч (Δ = %+.1f ч)"
                        % (total, r.norm_col, total - r.norm_col),
            ))
    return out


# --------------------------------------------------------------------------- #
#  Неизвестная должность (справочно)
# --------------------------------------------------------------------------- #
def check_unknown_position(result: ImportResult) -> List[Conflict]:
    out = []
    for r in result.rows:
        if r.week_norm is None:
            out.append(Conflict(
                code=UNKNOWN_POSITION, severity="warning", employee=r.name,
                message="не удалось определить недельную норму по должности %r"
                        % r.position,
            ))
    return out


def check_all(result: ImportResult, norm_tol: float = 1.0,
              sum_tol: float = 0.2) -> List[Conflict]:
    """Полный прогон всех проверок."""
    conflicts: List[Conflict] = []
    conflicts += check_unknown_position(result)
    conflicts += check_wrong_norm(result, norm_tol)
    conflicts += check_duplicate_rows(result)
    conflicts += check_overlaps(result)
    conflicts += check_missing_shorten(result)
    conflicts += check_hours_mismatch(result, sum_tol, norm_tol)
    return conflicts
