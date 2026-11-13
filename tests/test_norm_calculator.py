# -*- coding: utf-8 -*-
"""Тесты калькулятора норм (588н) и классификатора должностей."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.norm_calculator import (
    daily_hours, monthly_base_norm, monthly_individual_norm,
    deviation, year_norm, round_hours,
)
from app.services.position_classifier import classify, parse_rate, classify_with_rule

fails = 0
def check(name, actual, expected, tol=1e-6):
    global fails
    ok = abs(actual - expected) <= tol
    if not ok:
        fails += 1
    print(("OK  " if ok else "FAIL") + " %-44s = %r (ожид. %r)" % (name, actual, expected))


# --- daily_hours ----------------------------------------------------------- #
check("daily_hours 40", daily_hours(40), 8.0)
check("daily_hours 39", daily_hours(39), 7.8)
check("daily_hours 36", daily_hours(36), 7.2)
check("daily_hours 33", daily_hours(33), 6.6)
check("daily_hours 30", daily_hours(30), 6.0)

# --- месячная норма, ноябрь 2026 (20 раб., 1 предпраздн.) ----------------- #
check("ноябрь 2026 40ч", monthly_base_norm(40, 2026, 11), 159.0)
check("ноябрь 2026 39ч", monthly_base_norm(39, 2026, 11), 155.0)
check("ноябрь 2026 36ч", monthly_base_norm(36, 2026, 11), 143.0)
check("ноябрь 2026 33ч", monthly_base_norm(33, 2026, 11), 131.0)
check("ноябрь 2026 30ч", monthly_base_norm(30, 2026, 11), 119.0)

# ставка (rate)
check("ноябрь 2026 33ч x0.5", monthly_base_norm(33, 2026, 11, 0.5), 65.5)
check("ноябрь 2026 33ч x0.75", monthly_base_norm(33, 2026, 11, 0.75), 98.25)
check("ноябрь 2026 39ч x0.25", monthly_base_norm(39, 2026, 11, 0.25), 38.75)

# --- годовая норма 2026 ---------------------------------------------------- #
check("год 2026 40ч", year_norm(40, 2026), 1972.0)
check("год 2026 36ч", year_norm(36, 2026), 1774.4)
check("год 2026 24ч", year_norm(24, 2026), 1181.6)

# --- индивидуальная норма (вычет неявок) ----------------------------------- #
# ноябрь 2026: 20 раб.дней. 2,5,6 — обычные рабочие дни (не предпраздн.).
check("инд. норма 40ч, 0 неявок", monthly_individual_norm(40, 2026, 11), 159.0)
check("инд. норма 40ч, 3 неявки", monthly_individual_norm(40, 2026, 11, 1.0, [2, 5, 6]), 135.0)
# 3.11 — предпраздничный (сокращённый на 1 ч): неявка вычитается как 7 ч
check("инд. норма 40ч, неявка в предпраздн.", monthly_individual_norm(40, 2026, 11, 1.0, [3]), 152.0)
# 4.11 — праздник (нерабочий): не вычитается
check("инд. норма 40ч, неявка в праздник", monthly_individual_norm(40, 2026, 11, 1.0, [4]), 159.0)
# 1.11.2026 = воскресенье (нерабочий), не должен вычитаться
check("инд. норма 40ч, неявка в выходной", monthly_individual_norm(40, 2026, 11, 1.0, [1]), 159.0)

# --- отклонение ------------------------------------------------------------ #
check("deviation 160 vs 159", deviation(160.0, 159.0), 1.0)
check("round_hours 7.8", round_hours(7.8), 7.8)
check("round_hours 6.5999999", round_hours(6.5999999), 6.6)

# --- parse_rate ------------------------------------------------------------ #
check("rate '0,5 ед'", parse_rate("вр хир 0,5 ед"), 0.5)
check("rate '0.5 ед'", parse_rate("0.5 ед зав оомпдоу"), 0.5)
check("rate '0.75 ед'", parse_rate("0.75 ед вр офтальм"), 0.75)
check("rate '0,25 ед'", parse_rate("вр пед 0,25 ед"), 0.25)
check("rate '0.25 ед'", parse_rate("вр пед кзр 0.25 ед"), 0.25)
check("rate '025 ед' (опечатка)", parse_rate("025 ед вр хир дет"), 0.25)
check("rate '0.5ед.' (без пробела)", parse_rate("0.5ед. вр"), 0.5)
check("rate без ставки -> 1.0", parse_rate("зубной врач"), 1.0)
check("rate '0.75ед.   вр. ФТО'", parse_rate("0.75ед.   вр. ФТО"), 0.75)

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
for title, expected in CASES:
    got, rate = classify(title)
    check("norm %r" % title, got, expected)

# должность без однозначного правила
got, rate = classify("какой-то странный текст")
check("неизвестная должность -> None", got is None, True)

print("\nИТОГО ПРОВАЛОВ: %d" % fails)
sys.exit(1 if fails else 0)
