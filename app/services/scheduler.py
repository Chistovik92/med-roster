# -*- coding: utf-8 -*-
"""
Планирование графика: автосмены (заполнение пустых ячеек) и копирование графика
(синхронизация «врач ↔ медсестра» и др.).

Обе операции работают с уже импортированным :class:`ImportResult` in-memory и
пересчитывают итоговые часы сотрудника.
"""
from __future__ import annotations

from typing import List

from app.core.calendar_rf import get_year_calendar
from app.services.time_parser import parse_cell
from app.services.xls_importer import ImportResult, EmployeeRow


def _find_row(result: ImportResult, row_index: int) -> EmployeeRow:
    for r in result.rows:
        if r.index == row_index:
            return r
    raise ValueError("сотрудник с index=%r не найден" % row_index)


def autofill(result: ImportResult, row_index: int, shift: str,
             mode: str = "workdays") -> List[str]:
    """Заполнить пустые ячейки сотрудника заданной сменой (или кодом статуса).

    ``shift`` — строка смены («8-15,48») или код («В», «ОТ»…).

    ``mode``:
      * ``"workdays"`` — только рабочие дни по производственному календарю;
      * ``"empty"``    — все пустые ячейки месяца (включая выходные).

    Возвращает список предупреждений (например, «нет пустых ячеек»).
    """
    row = _find_row(result, row_index)
    shift = (shift or "").strip()
    if shift == "":
        raise ValueError("смена не задана")

    probe = parse_cell(shift)
    if probe.kind not in ("shift", "status"):
        raise ValueError("не удалось распознать смену %r" % shift)

    cal = get_year_calendar(result.year)
    filled = 0
    for day in range(1, result.day_count + 1):
        if row.raw_cells.get(day, "") != "":
            continue  # заполненные ячейки не трогаем
        if mode == "workdays":
            d = cal.day(result.month, day)
            if d is None or not d.is_work:
                continue
        row.raw_cells[day] = shift
        row.parsed[day] = parse_cell(shift)
        filled += 1

    row.total_hours = sum(p.total_hours for p in row.parsed.values())

    warnings: List[str] = []
    if filled == 0:
        warnings.append("нет пустых ячеек для заполнения (смена %r)" % shift)
    return warnings


def copy_schedule(result: ImportResult, from_index: int, to_index: int) -> None:
    """Скопировать все ячейки дней от одного сотрудника другому.

    Используется для синхронизации «врач ↔ медсестра»: график медсестры
    повторяет график врача. Приёмник полностью перезаписывается.
    """
    src = _find_row(result, from_index)
    dst = _find_row(result, to_index)
    if src.index == dst.index:
        raise ValueError("нельзя копировать график самому себе")

    for day in range(1, result.day_count + 1):
        raw = src.raw_cells.get(day, "")
        dst.raw_cells[day] = raw
        if raw == "":
            dst.parsed.pop(day, None)
        else:
            dst.parsed[day] = parse_cell(raw)
    dst.total_hours = sum(p.total_hours for p in dst.parsed.values())
