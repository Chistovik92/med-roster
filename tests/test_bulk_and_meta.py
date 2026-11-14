# -*- coding: utf-8 -*-
"""Тесты метаданных дней и массового добавления сотрудников.

Проверяем:
  * ``_days_meta`` — корректные день недели / выходной / сокращённый для
    ноября 2026 (3 ноября — предпраздничный рабочий, 4 ноября — праздник);
  * ``POST /api/session/{sid}/employees/bulk`` — массовое добавление с
    классификацией должностей и разбором ставки.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.main as main

fails = 0
def check(name, cond):
    global fails
    if not cond:
        fails += 1
    print(("OK  " if cond else "FAIL") + " %s" % name)


# ---- 1) метаданные дней ноября 2026 ----
res = main.create_manual_schedule(2026, 11)
meta = main._days_meta(res)
check("days_meta: 30 дней", len(meta) == 30)
# 1 ноября 2026 — воскресенье (выходной)
check("1 ноября — выходной (Вс)", meta[0]["off"] is True and meta[0]["weekday"] == "Вс")
# 3 ноября 2026 — вторник, рабочий, предпраздничный (сокращённый)
check("3 ноября — рабочий сокращённый (Вт)",
      meta[2]["weekday"] == "Вт" and meta[2]["off"] is False and meta[2]["short"] is True)
# 4 ноября 2026 — праздник (выходной)
check("4 ноября — праздник (выходной)", meta[3]["off"] is True)

# ---- 2) массовое добавление сотрудников ----
resp = main.create_schedule(year=2026, month=11)
payload = json.loads(resp.body.decode("utf-8"))
sid = payload["session_id"]
check("создана сессия", bool(sid))

resp = main.add_employees_bulk(sid, employees=[
    {"name": "Иванова И.И.", "position": "вр.пед.уч.", "rate": 1.0},
    {"name": "Петрова А.С.", "position": "м/с участковая", "rate": 0.5},
    {"name": "Сидоров П.П.", "position": "уборщик"},
    {"name": "", "position": "пустая строка"},  # должна быть пропущена
])
data = json.loads(resp.body.decode("utf-8"))
check("добавлено 3 сотрудника (пустая строка пропущена)", len(data["employees"]) == 3)

by_name = {e["name"]: e for e in data["employees"]}
check("педиатр — норма 39", by_name["Иванова И.И."]["week_norm"] == 39)
check("м/с — норма 39 и ставка 0.5",
      by_name["Петрова А.С."]["week_norm"] == 39 and by_name["Петрова А.С."]["rate"] == 0.5)
check("уборщик — норма 40 и ставка 1.0 (по умолчанию)",
      by_name["Сидоров П.П."]["week_norm"] == 40 and by_name["Сидоров П.П."]["rate"] == 1.0)

# days_meta присутствует в сериализации результата
check("в ответе есть days_meta", "days_meta" in data and len(data["days_meta"]) == 30)

print("\nИТОГО ПРОВАЛОВ: %d" % fails)
sys.exit(1 if fails else 0)
