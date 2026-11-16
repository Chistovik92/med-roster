# -*- coding: utf-8 -*-
"""Тесты метаданных дней и массового добавления сотрудников.

Проверяем:
  * ``_days_meta`` — корректные день недели / выходной / сокращённый для
    ноября 2026 (3 ноября — предпраздничный рабочий, 4 ноября — праздник);
  * ``POST /api/session/{sid}/employees/bulk`` — массовое добавление с
    классификацией должностей и разбором ставки.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.main as main


def test_days_meta_november_2026():
    res = main.create_manual_schedule(2026, 11)
    meta = main._days_meta(res)
    assert len(meta) == 30
    # 1 ноября 2026 — воскресенье (выходной)
    assert meta[0]["off"] is True
    assert meta[0]["weekday"] == "Вс"
    # 3 ноября 2026 — вторник, рабочий, предпраздничный (сокращённый)
    assert meta[2]["weekday"] == "Вт"
    assert meta[2]["off"] is False
    assert meta[2]["short"] is True
    # 4 ноября 2026 — праздник (выходной)
    assert meta[3]["off"] is True


def test_bulk_add_employees():
    resp = main.create_schedule(year=2026, month=11)
    payload = json.loads(resp.body.decode("utf-8"))
    sid = payload["session_id"]
    assert sid

    resp = main.add_employees_bulk(sid, employees=[
        {"name": "Иванова И.И.", "position": "вр.пед.уч.", "rate": 1.0},
        {"name": "Петрова А.С.", "position": "м/с участковая", "rate": 0.5},
        {"name": "Сидоров П.П.", "position": "уборщик"},
        {"name": "", "position": "пустая строка"},  # должна быть пропущена
    ])
    data = json.loads(resp.body.decode("utf-8"))
    assert len(data["employees"]) == 3

    by_name = {e["name"]: e for e in data["employees"]}
    assert by_name["Иванова И.И."]["week_norm"] == 39
    assert by_name["Петрова А.С."]["week_norm"] == 39
    assert by_name["Петрова А.С."]["rate"] == 0.5
    assert by_name["Сидоров П.П."]["week_norm"] == 40
    assert by_name["Сидоров П.П."]["rate"] == 1.0

    # days_meta присутствует в сериализации результата
    assert "days_meta" in data
    assert len(data["days_meta"]) == 30
