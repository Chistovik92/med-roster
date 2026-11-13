# -*- coding: utf-8 -*-
"""Тесты импорта .xls (xlrd) и вспомогательных функций."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.xls_importer import (
    import_xls, detect_period, _to_float, _to_str, COL_SUM, COL_NORM,
)

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

print("\nИТОГО ПРОВАЛОВ: %d" % fails)
sys.exit(1 if fails else 0)
