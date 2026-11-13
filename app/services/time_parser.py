# -*- coding: utf-8 -*-
"""
Парсер ячеек времени формата «СГП №16».

Формат записи рабочего времени в графике:
  * одиночный интервал:      ``8-15,48``   (8:00–15:48 = 7,8 ч)
  * интервал без минут:      ``8-12``, ``15-20``
  * разрывная смена с обедом: ``8-12 12.30-16.30`` (два интервала в ячейке)
  * время записывается как ``H`` или ``H[,.]MM`` — запятая или точка разделяет
    часы и минуты (НЕ десятичная дробь), без лидирующего нуля у часов:
    ``9,00`` = 9:00, ``14.36`` = 14:36, ``17,54`` = 17:54, ``20`` = 20:00.
  * опечатка вида ``16.00. 20`` исправляется на ``16.00-20`` (лишняя точка).

Коды статусов (неявки): ``В``, ``О``, ``ОТ``, ``Б``, ``У``, ``ПК``, ``Я``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.core.constants import STATUS_CODES

# Время: часы (1–2 цифры) и необязательные минуты через ',' или '.'.
# Минуты в исходных файлах всегда двузначные.
_TIME_RE = re.compile(r"^(\d{1,2})(?:[,.](\d{2}))?$")

# Исправление опечатки «16.00. 20» -> «16.00-20»: время с «висящей» точкой/запятой
# после минут, затем пробел и следующее время (без дефиса).
_BROKEN_SEP_RE = re.compile(r"(\d{1,2}[.,]\d{2})[.,]\s+(\d{1,2})(?!\d)")


@dataclass
class Interval:
    """Один непрерывный интервал рабочего времени (в минутах от полуночи)."""
    start: int
    end: int

    @property
    def minutes(self) -> int:
        return self.end - self.start

    @property
    def hours(self) -> float:
        return self.minutes / 60.0


@dataclass
class ParsedCell:
    """Результат разбора одной ячейки графика."""
    raw: str
    kind: str = "empty"                      # 'status' | 'shift' | 'empty' | 'invalid'
    status: Optional[str] = None             # канонический код статуса (kind == 'status')
    intervals: List[Interval] = field(default_factory=list)  # (kind == 'shift')
    total_minutes: int = 0
    total_hours: float = 0.0
    error: Optional[str] = None              # причина (kind == 'invalid')


def parse_time(token: str) -> Optional[int]:
    """Разобрать время вида ``H`` или ``H[,.]MM`` в минуты от полуночи.

    Возвращает ``None``, если строка не является временем.
    """
    t = (token or "").strip()
    m = _TIME_RE.match(t)
    if not m:
        return None
    hours = int(m.group(1))
    minutes = int(m.group(2)) if m.group(2) is not None else 0
    if hours > 23 or minutes > 59:
        return None
    return hours * 60 + minutes


def _normalize(raw: str) -> str:
    """Привести сырую строку ячейки к каноническому виду."""
    s = (raw or "").strip()
    # схлопнуть повторяющиеся пробелы
    s = re.sub(r"\s+", " ", s)
    # «16.00. 20» -> «16.00-20»
    s = _BROKEN_SEP_RE.sub(r"\1-\2", s)
    # убрать пробелы вокруг дефиса («8 - 15» -> «8-15»)
    s = re.sub(r"\s*-\s*", "-", s)
    return s.strip()


def parse_cell(value) -> ParsedCell:
    """Разобрать значение ячейки графика.

    Принимает строку (интервалы/код) или пустое/``None``. Числовые значения
    (например, сумма часов) не являются допустимым содержимым ежедневной ячейки
    и помечаются как ``invalid``.
    """
    if value is None:
        return ParsedCell(raw="")
    if isinstance(value, float) and value != value:  # NaN
        return ParsedCell(raw="", kind="empty")
    if not isinstance(value, str):
        return ParsedCell(raw=str(value), kind="invalid",
                          error="числовое значение вместо кода/интервала")

    raw = value.strip()
    if raw == "":
        return ParsedCell(raw=raw)

    # 1) код статуса (регистронезависимо)
    upper = raw.upper()
    if upper in STATUS_CODES:
        return ParsedCell(raw=raw, kind="status", status=STATUS_CODES[upper])

    # 2) интервалы времени
    norm = _normalize(raw)
    parts = [p for p in norm.split(" ") if p != ""]
    intervals: List[Interval] = []
    for part in parts:
        seg = part.split("-")
        if len(seg) != 2:
            return ParsedCell(raw=raw, kind="invalid",
                              error="не удалось разобрать сегмент: %r" % part)
        start = parse_time(seg[0])
        end = parse_time(seg[1])
        if start is None or end is None:
            return ParsedCell(raw=raw, kind="invalid",
                              error="неверное время в интервале: %r" % part)
        if end <= start:
            return ParsedCell(raw=raw, kind="invalid",
                              error="окончание раньше начала: %r" % part)
        intervals.append(Interval(start=start, end=end))

    total = sum(iv.minutes for iv in intervals)
    return ParsedCell(raw=raw, kind="shift", intervals=intervals,
                      total_minutes=total, total_hours=total / 60.0)


def is_status(value) -> bool:
    """Является ли значение ячейки кодом статуса (неявкой)."""
    return isinstance(value, str) and value.strip().upper() in STATUS_CODES


def format_minutes(minutes: int) -> str:
    """Оформить минуты в виде ``Ч:ММ`` (например, 468 -> '7:48')."""
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    return "%s%d:%02d" % (sign, minutes // 60, minutes % 60)


def format_hours(hours: float, ndigits: int = 1) -> str:
    """Оформить дробное число часов в вид «7,8» (запятая как десятичный знак)."""
    s = ("%%.%df" % ndigits) % hours
    return s.replace(".", ",")
