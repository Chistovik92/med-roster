# -*- coding: utf-8 -*-
"""Автокоррекция только детерминированных ошибок."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.autocorrect import autocorrect
from app.services.conflict_checker import (
    check_all, check_missing_shorten, OVERLAP, WRONG_NORM, DUPLICATE_ROW,
)
from app.services.time_parser import parse_cell
from app.services.xls_importer import EmployeeRow, ImportResult


def row(index, name, position="вр.пед.уч.", days=None, **kwargs):
    item = EmployeeRow(index=index, name=name, position=position,
                       rate=kwargs.pop("rate", 1.0),
                       week_norm=kwargs.pop("week_norm", 39), **kwargs)
    for day, value in (days or {}).items():
        item.raw_cells[day] = value
        item.parsed[day] = parse_cell(value)
    item.total_hours = sum(p.total_hours for p in item.parsed.values())
    return item


def result(rows):
    return ImportResult(source="test", year=2026, month=11, day_count=30, rows=rows)


def main():
    res = result([row(12, "Медведева К.Д.", norm_col=159.0, sum_col=1.0)])
    fixes = autocorrect(res)
    assert res.rows[0].norm_col == 155.0
    assert res.rows[0].sum_col == 0.0
    assert len(fixes) == 2
    assert not any(c.code == WRONG_NORM for c in check_all(res))

    days = {3: "12,12-20", 5: "12,12-20", 6: "12,12-20"}
    res = result([row(12, "Регистратор", "мед. регистр.", days, week_norm=40)])
    autocorrect(res)
    assert res.rows[0].raw_cells[3] == "12,12-19"
    assert check_missing_shorten(res) == []

    original = row(12, "Блохин И.С.", days={5: "8-15,48"})
    duplicate = row(13, "Блохин И.С.", days={5: "8-15,48"})
    res = result([original, duplicate])
    autocorrect(res)
    assert len(res.rows) == 1
    assert not any(c.code == DUPLICATE_ROW for c in check_all(res))

    res = result([
        row(12, "Макарова Н.В.", days={3: "8-15,48"}),
        row(13, "Макарова Н.В.", "0,5 ед мс уч", {3: "12,12-20"}),
    ])
    autocorrect(res)
    assert any(c.code == OVERLAP for c in check_all(res)), "накладку нельзя угадывать"
    print("OK  автокоррекция: норма, сумма, предпраздник, дубликат; накладка оставлена")


if __name__ == "__main__":
    main()
