# -*- coding: utf-8 -*-
"""
Импорт графика из файла ``.xls`` (формат «СГП №16», Лист1).

Структура Лист1:
  * строки 0–10 — «шапка» (УТВЕРЖДАЮ, название, период «на ноябрь 2026 года»);
  * строка 11   — заголовки колонок: c0='Ф.И.О.', c2..c31 = дни 1..30, c34='Прим.';
  * строки 12+  — данные: c0=ФИО, c1=должность/ставка, c2..c31=ячейки дней,
                  c32=сумма часов, c33=доп. колонка, c34=«Прим.» (норма).

Зависимость: ``xlrd`` (для ``.xls`` нужна версия 1.2.0 или 2.x; файл читается
напрямую через xlrd, НЕ через pandas).
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.services.position_classifier import classify, classify_with_rule
from app.services.time_parser import parse_cell, ParsedCell

# Номер колонки ФИО / должности (0-based).
COL_NAME = 0
COL_POSITION = 1
COL_SUM = 32
COL_EXTRA = 33
COL_NORM = 34

# Первая строка с данными (заголовок на строке 11, данные — с 12).
FIRST_DATA_ROW = 12

# Русские названия месяцев (для автоопределения периода из «шапки»).
_MONTHS_RU = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "май": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}
_PERIOD_RE = re.compile(r"(январ[ья]|феврал[ья]|март[а]?|апрел[ья]|ма[йя]|июн[ья]|"
                        r"июл[ья]|август[а]?|сентябр[ья]|октябр[ья]|ноябр[ья]|декабр[ья])"
                        r"\D{0,4}(\d{4})", re.IGNORECASE)


@dataclass
class EmployeeRow:
    """Одна строка графика (один сотрудник)."""
    index: int                              # исходный номер строки в листе (0-based)
    name: str
    position: str
    rate: float = 1.0
    week_norm: Optional[int] = None         # недельная норма по классификатору
    norm_rule: Optional[str] = None         # сработавшее правило классификации
    raw_cells: Dict[int, str] = field(default_factory=dict)   # день -> сырая строка
    parsed: Dict[int, ParsedCell] = field(default_factory=dict)  # день -> разбор
    total_hours: float = 0.0                # сумма часов по интервалам
    sum_col: Optional[float] = None         # c32 (сумма часов)
    norm_col: Optional[float] = None        # c34 («Прим.» — норма)
    extra_col: Optional[str] = None         # c33 (доп. колонка)


@dataclass
class ImportResult:
    """Результат импорта одного файла."""
    source: str
    year: int
    month: int
    day_count: int
    rows: List[EmployeeRow] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _to_float(value) -> Optional[float]:
    """Привести значение ячейки к float (None, если не число)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _to_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN
        return ""
    # Число 0,0 в ячейке расписания — эквивалент пустой ячейки (xlrd отдаёт
    # пустые текстовые ячейки как ''; но числовые пустые — как 0.0).
    if isinstance(value, float) and value == 0.0:
        return ""
    return str(value).strip()


def _open_workbook(source):
    """Открыть книгу из пути к файлу или из байтов (``bytes``/``bytearray``).

    Поддержка байтов позволяет импортировать загруженный файл без записи во
    временный файл (на Windows это убирает проблемы с блокировкой файла).
    """
    import xlrd
    if isinstance(source, (bytes, bytearray)):
        return xlrd.open_workbook(file_contents=bytes(source))
    return xlrd.open_workbook(source)


def detect_period(source) -> Tuple[Optional[int], Optional[int]]:
    """Автоопределить (год, месяц) из «шапки» файла.

    ``source`` — путь к файлу или байты (``bytes``). Ищет в первых строках
    шаблон вида «ноябрь 2026 года». Возвращает ``(year, month)`` или
    ``(None, None)``, если не найдено.
    """
    wb = _open_workbook(source)
    sh = wb.sheet_by_index(0)
    for r in range(0, min(sh.nrows, FIRST_DATA_ROW)):
        for c in range(0, sh.ncols):
            v = _to_str(sh.cell_value(r, c))
            m = _PERIOD_RE.search(v)
            if m:
                month = None
                name = m.group(1).lower()
                for prefix, num in _MONTHS_RU.items():
                    if name.startswith(prefix):
                        month = num
                        break
                year = int(m.group(2))
                if month:
                    return year, month
    return None, None


def import_xls(source, year: Optional[int] = None,
               month: Optional[int] = None,
               filename: Optional[str] = None) -> ImportResult:
    """Импортировать график из ``.xls``.

    ``source`` — путь к файлу или байты (``bytes``); ``filename`` — имя файла
    для отображения (когда передаются байты). Если ``year``/``month`` не заданы,
    период определяется из «шапки» файла. Возвращает :class:`ImportResult`.
    """
    if year is None or month is None:
        d_year, d_month = detect_period(source)
        year = year if year is not None else d_year
        month = month if month is not None else d_month
    if year is None or month is None:
        raise ValueError("Не удалось определить период (укажите year/month явно)")

    day_count = calendar.monthrange(year, month)[1]

    wb = _open_workbook(source)
    sh = wb.sheet_by_index(0)
    src_name = filename or (source if isinstance(source, str) else "upload.xls")
    result = ImportResult(source=src_name, year=year, month=month,
                          day_count=day_count)

    for r in range(FIRST_DATA_ROW, sh.nrows):
        name = _to_str(sh.cell_value(r, COL_NAME))
        position = _to_str(sh.cell_value(r, COL_POSITION))
        if name == "":
            # строка без ФИО — пропускаем (пустая или итоговая), но логируем
            if position != "" or _to_str(sh.cell_value(r, COL_NORM)) != "":
                result.warnings.append("строка %d: нет ФИО, пропущена" % (r + 1))
            continue

        week_norm, rate, rule = classify_with_rule(position)
        row = EmployeeRow(index=r, name=name, position=position,
                          rate=rate, week_norm=week_norm, norm_rule=rule)

        # ячейки дней: день d (1-based) -> колонка d+1
        for d in range(1, day_count + 1):
            raw = _to_str(sh.cell_value(r, d + 1))
            row.raw_cells[d] = raw
            if raw != "":
                row.parsed[d] = parse_cell(raw)

        row.total_hours = sum(p.total_hours for p in row.parsed.values())
        row.sum_col = _to_float(sh.cell_value(r, COL_SUM))
        row.norm_col = _to_float(sh.cell_value(r, COL_NORM))
        row.extra_col = _to_str(sh.cell_value(r, COL_EXTRA))

        result.rows.append(row)

    return result
