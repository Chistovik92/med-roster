# -*- coding: utf-8 -*-
"""Автоматическое исправление ошибок с детерминированной схемой.

Исправляются только значения, для которых ожидаемый результат известен:
норма по 588н, итоговая сумма, точный дубликат и предпраздничная смена.
Пересечения ставок и неизвестные должности требуют решения пользователя.
"""
from __future__ import annotations

from typing import Dict, List

from app.services.conflict_checker import (
    check_missing_shorten, normalize_name,
)
from app.services.norm_calculator import monthly_base_norm
from app.services.time_parser import parse_cell
from app.services.xls_importer import EmployeeRow, ImportResult


def _action(row: EmployeeRow, code: str, message: str, day=None) -> Dict:
    return {"code": code, "employee": row.name, "day": day, "message": message}


def _set_cell(row: EmployeeRow, day: int, value: str) -> None:
    row.raw_cells[day] = value
    if value:
        row.parsed[day] = parse_cell(value)
    else:
        row.parsed.pop(day, None)
    row.total_hours = sum(p.total_hours for p in row.parsed.values())


def _fmt_time(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    return str(hours) if mins == 0 else "%d,%02d" % (hours, mins)


def _shorten_last_interval(row: EmployeeRow, day: int) -> bool:
    pc = row.parsed.get(day)
    if pc is None or pc.kind != "shift" or not pc.intervals:
        return False
    last = pc.intervals[-1]
    if last.end - 60 <= last.start:
        return False
    last.end -= 60
    value = " ".join("%s-%s" % (_fmt_time(iv.start), _fmt_time(iv.end))
                     for iv in pc.intervals)
    _set_cell(row, day, value)
    return True


def autocorrect(result: ImportResult) -> List[Dict]:
    """Исправить график на месте и вернуть список выполненных действий."""
    actions: List[Dict] = []

    # Точные дубликаты удаляем до остальных исправлений.
    seen = {}
    unique_rows = []
    for row in result.rows:
        key = (normalize_name(row.name), row.position,
               tuple(sorted(row.raw_cells.items())))
        if key in seen:
            actions.append(_action(
                row, "duplicate_row",
                "удалён точный дубликат строки %d" % (row.index + 1)))
            continue
        seen[key] = row
        unique_rows.append(row)
    result.rows = unique_rows

    for row in result.rows:
        if row.week_norm is not None and row.norm_col is not None:
            expected = round(monthly_base_norm(
                row.week_norm, result.year, result.month, row.rate), 1)
            if abs(expected - row.norm_col) > 1.0:
                old = row.norm_col
                row.norm_col = expected
                actions.append(_action(
                    row, "wrong_norm",
                    "норма изменена с %g на %g" % (old, expected)))

        if row.sum_col is not None and abs(row.total_hours - row.sum_col) > 0.2:
            old = row.sum_col
            row.sum_col = round(row.total_hours, 1)
            actions.append(_action(
                row, "hours_mismatch",
                "сумма в колонке 32 изменена с %g на %g" % (old, row.sum_col)))

    # Берём только найденные валидатором предпраздничные смены: эвристика
    # сравнения с обычной длительностью остаётся единой для ручной проверки и fix.
    for conflict in list(check_missing_shorten(result)):
        for row in result.rows:
            if normalize_name(row.name) != normalize_name(conflict.employee or ""):
                continue
            if _shorten_last_interval(row, conflict.day):
                actions.append(_action(
                    row, conflict.code,
                    "окончание предпраздничной смены перенесено на 1 час раньше",
                    conflict.day))
                if row.sum_col is not None:
                    row.sum_col = round(row.total_hours, 1)
            break

    return actions
