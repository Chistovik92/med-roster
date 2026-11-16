# -*- coding: utf-8 -*-
"""Тесты локального хранилища сохранённых графиков (SQLite)."""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# изолируем БД в временную папку
_TMP = tempfile.mkdtemp(prefix="med-roster-test-")
os.environ["MEDROSTER_DATA_DIR"] = _TMP

from app.core import storage
from app.services.xls_importer import (
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


def make_result(year=2026, month=11):
    res = create_manual_schedule(year, month)
    row = EmployeeRow(index=0, name="Иванов И.И.", position="вр.пед.уч.",
                      rate=1.0, week_norm=39)
    row.raw_cells[2] = "8-15,48"
    row.parsed[2] = parse_cell("8-15,48")
    row.total_hours = 7.8
    res.rows.append(row)
    return res


res = make_result()
res.department = "УПО"
payload = serialize_result(res)

saved_id = storage.save_month(res.year, res.month, "ГУЗ «СГП № 16»", payload)
check("save возвращает id > 0", saved_id > 0, True)

lst = storage.list_saved()
check("list_saved: одна запись", len(lst), 1)
check("list_saved: year", lst[0]["year"], 2026)
check("list_saved: month", lst[0]["month"], 11)
check("list_saved: org", lst[0]["org"], "ГУЗ «СГП № 16»")
check("list_saved: employee_count", lst[0]["employee_count"], 1)
check("list_saved: dept", lst[0]["dept"], "УПО")

data = storage.get_saved(saved_id)
check("get_saved: employees", len(data["employees"]), 1)
restored = deserialize_result(data)
check("restored: имя", restored.rows[0].name, "Иванов И.И.")
check("restored: норма", restored.rows[0].week_norm, 39)
check("restored: часы", round(restored.rows[0].total_hours, 1), 7.8)
check("restored: manual", restored.manual, True)
check("restored: подразделение", restored.department, "УПО")

check("delete_saved: True", storage.delete_saved(saved_id), True)
check("delete_saved повторно: False", storage.delete_saved(saved_id), False)
check("get_saved после удаления: None", storage.get_saved(saved_id), None)
check("list_saved после удаления: пусто", storage.list_saved(), [])

shutil.rmtree(_TMP, ignore_errors=True)
print("\nИТОГО ПРОВАЛОВ: %d" % fails)
sys.exit(1 if fails else 0)
