# -*- coding: utf-8 -*-
"""Тесты валидатора (5 типов ошибок) на синтетических данных."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.xls_importer import ImportResult, EmployeeRow
from app.services.time_parser import parse_cell
from app.services.conflict_checker import (
    check_wrong_norm, check_overlaps, check_missing_shorten,
    check_duplicate_rows, check_hours_mismatch, check_unknown_position,
    check_all, WRONG_NORM, OVERLAP, MISSING_SHORTEN, DUPLICATE_ROW,
    HOURS_MISMATCH, UNKNOWN_POSITION, normalize_name,
)


def mk_row(index, name, position, days=None, week_norm=39, rate=1.0,
           sum_col=None, norm_col=None):
    row = EmployeeRow(index=index, name=name, position=position,
                      rate=rate, week_norm=week_norm)
    if days:
        for d, val in days.items():
            row.raw_cells[d] = val
            row.parsed[d] = parse_cell(val)
    row.total_hours = sum(p.total_hours for p in row.parsed.values())
    row.sum_col = sum_col
    row.norm_col = norm_col
    return row


def res_for(rows, year=2026, month=11, day_count=30):
    return ImportResult(source="synthetic", year=year, month=month,
                        day_count=day_count, rows=rows)


# --- normalize_name --------------------------------------------------------- #
def test_normalize_name():
    assert normalize_name(" Афанасьева  И. Н. ") == "афанасьева и.н."


# --- тип 1: неверная норма в «Прим.» --------------------------------------- #
def test_wrong_norm():
    res = res_for([mk_row(12, "Медведева К.Д.", "вр.пед.уч.", week_norm=39,
                          rate=1.0, norm_col=159.0)])  # должно быть 155
    c = check_wrong_norm(res)
    assert any(x.code == WRONG_NORM for x in c)
    # корректная норма не должна флагаться
    res2 = res_for([mk_row(12, "Симонова Н.А.", "вр.пед.уч.", week_norm=39,
                           rate=1.0, norm_col=155.0)])
    assert check_wrong_norm(res2) == []


# --- тип 2: накладка интервалов ставок ------------------------------------- #
def test_overlap_detected():
    res = res_for([
        mk_row(12, "Макарова Н.В.", "вр.пед.уч.", days={3: "8-15,48"}),
        mk_row(13, "Макарова Н.В.", "0,5 ед мс уч", days={3: "12,12-20"}),
    ])
    c = check_overlaps(res)
    assert any(x.code == OVERLAP and x.day == 3 for x in c)


def test_overlap_not_detected():
    res = res_for([
        mk_row(12, "Прусова С.А.", "вр.пед.уч.", days={5: "8-12"}),
        mk_row(13, "Прусова С.А.", "0,5 ед мс уч", days={5: "13-20"}),
    ])
    assert check_overlaps(res) == []


# --- тип 3: забытое сокращение предпраздничного дня ------------------------ #
def test_missing_shorten_detected():
    days = {5: "12,12-20", 6: "12,12-20", 9: "12,12-20", 10: "12,12-20"}
    days[3] = "12,12-20"
    res = res_for([mk_row(12, "Регистратор", "мед. регистр.", days=days, week_norm=40)])
    c = check_missing_shorten(res)
    assert any(x.code == MISSING_SHORTEN and x.day == 3 for x in c)


def test_missing_shorten_not_detected_when_shortened():
    days = {5: "12,12-20", 6: "12,12-20", 9: "12,12-20", 10: "12,12-20"}
    days[3] = "12,12-19"
    res = res_for([mk_row(12, "Регистратор", "мед. регистр.", days=days, week_norm=40)])
    assert check_missing_shorten(res) == []


# --- тип 4: дублирование строк --------------------------------------------- #
def test_duplicate_rows():
    days = {5: "8-15,48", 6: "12,12-20"}
    res = res_for([
        mk_row(12, "Блохин И.С.", "0,5 ед м/с", days=days),
        mk_row(13, "Блохин И.С.", "0,5 ед м/с", days=days),
    ])
    c = check_duplicate_rows(res)
    assert any(x.code == DUPLICATE_ROW for x in c)


# --- тип 5: расхождение сумм часов ----------------------------------------- #
def test_hours_mismatch():
    res = res_for([mk_row(12, "Иванов И.И.", "зубной врач", week_norm=33,
                          days={5: "8-15,48", 6: "12,12-20"}, sum_col=20.0)])  # факт 15.6
    c = check_hours_mismatch(res)
    assert any(x.code == HOURS_MISMATCH for x in c)


# --- неизвестная должность -------------------------------------------------- #
def test_unknown_position():
    res = res_for([mk_row(12, "Петров П.П.", "", week_norm=None)])
    assert any(x.code == UNKNOWN_POSITION for x in check_unknown_position(res))


# --- расчётная норма для ручных строк (без колонки «Прим.») ----------------- #
def test_manual_row_computed_norm_deviation():
    res = res_for([mk_row(12, "Ручной", "вр.пед.уч.", week_norm=39, rate=0.5,
                          days={5: "8-15,48", 6: "12,12-20"})])  # факт 15.6
    c = check_hours_mismatch(res)
    assert any(x.code == HOURS_MISMATCH for x in c)


def test_manual_row_skew_flagged():
    res = res_for([mk_row(12, "Точный", "вр.пед.уч.", week_norm=39, rate=0.5,
                          days={d: "8-15,48" for d in range(1, 31)})])
    c = check_hours_mismatch(res)
    assert len(c) >= 1


# --- полный прогон не падает и собирает все типы --------------------------- #
def test_check_all_collects_types():
    big = res_for([
        mk_row(12, "Медведева К.Д.", "вр.пед.уч.", week_norm=39, norm_col=159.0),
        mk_row(13, "Макарова Н.В.", "вр.пед.уч.", days={3: "8-15,48"}),
        mk_row(14, "Макарова Н.В.", "0,5 ед мс уч", days={3: "12,12-20"}),
    ])
    allc = check_all(big)
    codes = {x.code for x in allc}
    assert WRONG_NORM in codes
    assert OVERLAP in codes
