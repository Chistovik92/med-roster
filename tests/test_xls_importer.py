# -*- coding: utf-8 -*-
"""Тесты импорта .xls (xlrd) и вспомогательных функций."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.xls_importer import (
    import_xls, detect_period, _to_float, _to_str, COL_SUM, COL_NORM,
    create_manual_schedule, serialize_result, deserialize_result, EmployeeRow,
)
from app.services.time_parser import parse_cell

fails = 0
def check(name, actual, expected):
    global fails
    ok = (actual == expected)
    if not ok:
        fails += 1
    print(("OK  " if ok else "FAIL") + " %-46s = %r (ожид. %r)" % (name, actual, expected))


# --- вспомогательные ------------------------------------------------------- #
check("_to_float None", _to_float(None), None)
check("_to_float ''", _to_float(""), None)
check("_to_float '60'", _to_float("60"), 60.0)
check("_to_float '60,5'", _to_float("60,5"), 60.5)
check("_to_float 131.0", _to_float(131.0), 131.0)
check("_to_float 'abc'", _to_float("abc"), None)
check("_to_str None", _to_str(None), "")
check("_to_str ' В '", _to_str(" В "), "В")

# --- импорт реальных файлов (пропуск, если файлов нет в репозитории) -------- #
FILES = [
    ("ноябрь  2026  общий.xls", 79, {33: 18, 39: 36, 36: 4, 40: 20, None: 1}),
    ("ноябрь  УПО 2026.xls", 17, {39: 17}),
]
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
missing = 0
for fn, nrows, norm_dist in FILES:
    path = os.path.join(BASE, fn)
    if not os.path.exists(path):
        missing += 1
        print("SKIP (нет файла) %s" % fn)
        continue
    res = import_xls(path)
    check("%s период" % fn, (res.year, res.month), (2026, 11))
    check("%s дней" % fn, res.day_count, 30)
    check("%s строк" % fn, len(res.rows), nrows)
    from collections import Counter
    got_dist = dict(Counter(r.week_norm for r in res.rows))
    check("%s распределение норм" % fn, got_dist, norm_dist)

    # контрольные суммы часов конкретных сотрудников
    by_name = {r.name: r for r in res.rows}
    for nm, exp_sum, exp_norm in [("Азарнова Е.С.", 131.0, 131.0)]:
        if nm in by_name:
            check("%s: %s часов" % (fn, nm), round(by_name[nm].total_hours, 1), exp_sum)
            check("%s: %s норма" % (fn, nm), by_name[nm].norm_col, exp_norm)

if missing:
    print("\n(пропущено файлов: %d — .xls не в git, только локально)" % missing)


# --- ручной график: создание и сериализация --------------------------------- #
res = create_manual_schedule(2026, 11)
check("create_manual: manual=True", res.manual, True)
check("create_manual: year", res.year, 2026)
check("create_manual: month", res.month, 11)
check("create_manual: day_count", res.day_count, 30)
check("create_manual: пусто", res.rows, [])

row = EmployeeRow(index=0, name="Смирнова О.А.", position="зубной врач",
                  rate=0.5, week_norm=33)
row.raw_cells[2] = "8-15,48"
row.parsed[2] = parse_cell("8-15,48")
row.total_hours = 7.8
res.rows.append(row)

data = serialize_result(res)
check("serialize: employees", len(data["employees"]), 1)
check("serialize: rate сохранён", data["employees"][0]["rate"], 0.5)
check("serialize: week_norm сохранён", data["employees"][0]["week_norm"], 33)
check("serialize: days сохранены", data["employees"][0]["days"], {"2": "8-15,48"})

res2 = deserialize_result(data)
check("deserialize: имя", res2.rows[0].name, "Смирнова О.А.")
check("deserialize: ставка", res2.rows[0].rate, 0.5)
check("deserialize: норма", res2.rows[0].week_norm, 33)
check("deserialize: часы", round(res2.rows[0].total_hours, 1), 7.8)
check("deserialize: manual", res2.manual, True)

print("\nИТОГО ПРОВАЛОВ: %d" % fails)
sys.exit(1 if fails else 0)
