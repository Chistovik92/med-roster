# -*- coding: utf-8 -*-
"""Тесты калькулятора норм (588н) и классификатора должностей."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.norm_calculator import (
    daily_hours, monthly_base_norm, monthly_individual_norm,
    deviation, year_norm, round_hours,
)
from app.services.position_classifier import classify, parse_rate, classify_with_rule  # noqa: F401


# --- daily_hours ----------------------------------------------------------- #
def test_daily_hours():
    assert daily_hours(40) == 8.0
    assert daily_hours(39) == 7.8
    assert daily_hours(36) == 7.2
    assert daily_hours(33) == 6.6
    assert daily_hours(30) == 6.0


# --- месячная норма, ноябрь 2026 (20 раб., 1 предпраздн.) ----------------- #
def test_monthly_base_norm_november_2026():
    assert monthly_base_norm(40, 2026, 11) == 159.0
    assert monthly_base_norm(39, 2026, 11) == 155.0
    assert monthly_base_norm(36, 2026, 11) == 143.0
    assert monthly_base_norm(33, 2026, 11) == 131.0
    assert monthly_base_norm(30, 2026, 11) == 119.0


def test_monthly_base_norm_rate():
    assert monthly_base_norm(33, 2026, 11, 0.5) == 65.5
    assert monthly_base_norm(33, 2026, 11, 0.75) == 98.25
    assert monthly_base_norm(39, 2026, 11, 0.25) == 38.75


# --- годовая норма 2026 ---------------------------------------------------- #
def test_year_norm_2026():
    assert year_norm(40, 2026) == 1972.0
    assert year_norm(36, 2026) == 1774.4
    assert year_norm(24, 2026) == 1181.6


# --- индивидуальная норма (вычет неявок) ----------------------------------- #
def test_monthly_individual_norm():
    assert monthly_individual_norm(40, 2026, 11) == 159.0
    assert monthly_individual_norm(40, 2026, 11, 1.0, [2, 5, 6]) == 135.0
    # 3.11 — предпраздничный (сокращённый на 1 ч): неявка вычитается как 7 ч
    assert monthly_individual_norm(40, 2026, 11, 1.0, [3]) == 152.0
    # 4.11 — праздник (нерабочий): не вычитается
    assert monthly_individual_norm(40, 2026, 11, 1.0, [4]) == 159.0
    # 1.11.2026 = воскресенье (нерабочий), не должен вычитаться
    assert monthly_individual_norm(40, 2026, 11, 1.0, [1]) == 159.0


# --- отклонение ------------------------------------------------------------ #
def test_deviation_and_round():
    assert deviation(160.0, 159.0) == 1.0
    assert round_hours(7.8) == 7.8
    assert round_hours(6.5999999) == 6.6


# --- parse_rate ------------------------------------------------------------ #
def test_parse_rate():
    assert parse_rate("вр хир 0,5 ед") == 0.5
    assert parse_rate("0.5 ед зав оомпдоу") == 0.5
    assert parse_rate("0.75 ед вр офтальм") == 0.75
    assert parse_rate("вр пед 0,25 ед") == 0.25
    assert parse_rate("вр пед кзр 0.25 ед") == 0.25
    assert parse_rate("025 ед вр хир дет") == 0.25
    assert parse_rate("0.5ед. вр") == 0.5
    assert parse_rate("зубной врач") == 1.0
    assert parse_rate("0.75ед.   вр. ФТО") == 0.75


# --- classify (недельная норма по должности) ------------------------------- #
CASES = [
    ("вр.ф.д.", 33), ("зубной врач", 33), ("вр офтальм", 33), ("вр эндокр 0,5 ед", 33),
    ("вр хир 0,5 ед", 33), ("вр.ак.гин.", 33), ("вр кардиол", 33), ("Врач-неврол.", 33),
    ("вр УЗИ", 33), ("врач ЛФК", 33), ("вр.дн.стац.", 33), ("вр. оторинол 0.5 ед", 33),
    ("0,5 ед вр офт", 33), ("025 ед вр уролог", 33),
    ("вр.ифекц.", 36), ("фельд. лаборант", 36), ("0,5 ед фел лаб", 36),
    ("вр.пед.уч.", 39), ("вр пед 0,25 ед", 39), ("0.5 ед вр пед уч", 39),
    ("вр пед зав отд", 39), ("вр.пед ООМПДОУ", 39), ("м/с", 39), ("м/с оомпдоу", 39),
    ("м.с проц", 39), ("уч. м/с", 39), ("старш. м/с", 39), ("м/с по массажу", 39),
    ("ст мс ООМПДОУ", 39), ("м.с фун.д.", 39),
    ("мед. регистр.", 40), ("опер. ЭВМ", 40), ("оператор", 40), ("уб.пом.", 40),
    ("0.75 ед гардероб", 40), ("уб.тер.", 40),
    ("0.5 ед зав оомпдоу", 39),
]


def test_classify_cases():
    for title, expected in CASES:
        got, rate = classify(title)
        assert got == expected, "norm %r" % title


def test_classify_unknown():
    got, rate = classify("какой-то странный текст")
    assert got is None
