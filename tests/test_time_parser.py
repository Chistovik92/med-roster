# -*- coding: utf-8 -*-
"""Тесты парсера времени (формат «СГП №16»)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.time_parser import parse_cell, parse_time, format_minutes, format_hours


# --- parse_time ------------------------------------------------------------ #
def test_parse_time_basic():
    assert parse_time("8") == 480
    assert parse_time("20") == 1200
    assert parse_time("9,00") == 540
    assert parse_time("14.36") == 876
    assert parse_time("17,54") == 1074
    assert parse_time("15,48") == 948
    assert parse_time("12,12") == 732
    assert parse_time("11,24") == 684
    assert parse_time("13,36") == 816


def test_parse_time_invalid():
    assert parse_time("abc") is None
    assert parse_time("8,5") is None       # минуты одним знаком
    assert parse_time("25,00") is None     # > 23 ч
    assert parse_time("8,60") is None      # мин > 59


# --- parse_cell: интервалы ------------------------------------------------- #
def test_parse_cell_intervals():
    c = parse_cell("8-15,48")
    assert c.kind == "shift"
    assert c.total_minutes == 468
    assert round(c.total_hours, 3) == 7.8

    assert parse_cell("12,12-20").total_minutes == 468
    assert parse_cell("8-14,36").total_minutes == 396   # 6:36
    assert parse_cell("8-12").total_minutes == 240
    assert parse_cell("15-20").total_minutes == 300
    assert parse_cell("9,00-15").total_minutes == 360
    assert parse_cell("14.36-17,54").total_minutes == 198   # смешанные точка/запятая
    assert parse_cell("13,36-15,54").total_minutes == 138
    assert parse_cell("13,12-20").total_minutes == 408


def test_parse_cell_split_shift():
    c = parse_cell("8-12 12.30-16.30")
    assert c.kind == "shift"
    assert len(c.intervals) == 2
    assert c.total_minutes == 240 + 240


# --- parse_cell: опечатка «16.00. 20» -------------------------------------- #
def test_parse_cell_typo():
    c = parse_cell("16.00. 20")
    assert c.kind == "shift"
    assert c.intervals[0].start == 16 * 60
    assert c.intervals[0].end == 20 * 60
    assert c.total_minutes == 240


def test_parse_cell_spaces_around_dash():
    c = parse_cell("8 - 15")
    assert (c.kind, c.total_minutes) == ("shift", 420)


# --- parse_cell: коды статусов --------------------------------------------- #
def test_parse_cell_status_codes():
    for code, canon in [("В", "day_off"), ("О", "vacation"), ("ОТ", "vacation"),
                        ("Б", "sick"), ("У", "study"), ("ПК", "study"), ("Я", "present")]:
        c = parse_cell(code)
        assert (c.kind, c.status) == ("status", canon)
    c = parse_cell("в")  # регистронезависимо
    assert (c.kind, c.status) == ("status", "day_off")


# --- parse_cell: пустые / некорректные ------------------------------------- #
def test_parse_cell_empty_and_invalid():
    assert parse_cell("").kind == "empty"
    assert parse_cell(None).kind == "empty"
    assert parse_cell("   ").kind == "empty"
    assert parse_cell(131.0).kind == "invalid"
    assert parse_cell("8--15").kind == "invalid"
    assert parse_cell("20-8").kind == "invalid"
    assert parse_cell("xyz").kind == "invalid"


# --- вспомогательные ------------------------------------------------------- #
def test_formatters():
    assert format_minutes(468) == "7:48"
    assert format_minutes(60) == "1:00"
    assert format_hours(7.8) == "7,8"
    assert format_hours(6.0) == "6,0"
