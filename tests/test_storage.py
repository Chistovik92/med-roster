# -*- coding: utf-8 -*-
"""Тесты локального хранилища сохранённых графиков (SQLite)."""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

# изолируем БД во временную папку на время модуля
_TMP = tempfile.mkdtemp(prefix="med-roster-test-")


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    monkeypatch.setenv("MEDROSTER_DATA_DIR", _TMP)


from app.core import storage  # noqa: E402
from app.services.xls_importer import (  # noqa: E402
    create_manual_schedule, serialize_result, deserialize_result, EmployeeRow,
)
from app.services.time_parser import parse_cell  # noqa: E402


def make_result(year=2026, month=11):
    res = create_manual_schedule(year, month)
    row = EmployeeRow(index=0, name="Иванов И.И.", position="вр.пед.уч.",
                      rate=1.0, week_norm=39)
    row.raw_cells[2] = "8-15,48"
    row.parsed[2] = parse_cell("8-15,48")
    row.total_hours = 7.8
    res.rows.append(row)
    return res


def test_save_and_list():
    res = make_result()
    res.department = "УПО"
    payload = serialize_result(res)

    saved_id = storage.save_month(res.year, res.month, "ГУЗ «СГП № 16»", payload)
    assert saved_id > 0

    lst = storage.list_saved()
    assert len(lst) == 1
    assert lst[0]["year"] == 2026
    assert lst[0]["month"] == 11
    assert lst[0]["org"] == "ГУЗ «СГП № 16»"
    assert lst[0]["employee_count"] == 1
    assert lst[0]["dept"] == "УПО"

    data = storage.get_saved(saved_id)
    assert len(data["employees"]) == 1
    restored = deserialize_result(data)
    assert restored.rows[0].name == "Иванов И.И."
    assert restored.rows[0].week_norm == 39
    assert round(restored.rows[0].total_hours, 1) == 7.8
    assert restored.manual is True
    assert restored.department == "УПО"

    storage.delete_saved(saved_id)


def test_rename_and_update():
    res = make_result()
    res.department = "УПО"
    payload = serialize_result(res)
    saved_id = storage.save_month(res.year, res.month, "ГУЗ «СГП № 16»", payload)

    assert storage.rename_saved(saved_id, "Ноябрьский график") is True
    assert storage.list_saved()[0]["title"] == "Ноябрьский график"

    res.rows[0].raw_cells[3] = "9-17"
    res.rows[0].parsed[3] = parse_cell("9-17")
    res.rows[0].total_hours = 15.8
    payload_updated = serialize_result(res)
    assert storage.update_saved(saved_id, "ГУЗ «СГП № 16»", "УПО", payload_updated) is True

    restored_updated = deserialize_result(storage.get_saved(saved_id))
    assert round(restored_updated.rows[0].total_hours, 1) == 15.8
    assert len(storage.list_saved()) == 1

    storage.delete_saved(saved_id)


def test_export_import_database():
    res = make_result()
    res.department = "УПО"
    payload = serialize_result(res)
    saved_id = storage.save_month(res.year, res.month, "ГУЗ «СГП № 16»", payload)

    export_path = storage.export_database()
    assert os.path.isfile(export_path)
    external = os.path.join(_TMP, "external.db")
    shutil.copyfile(export_path, external)

    # повторно ничего не добавлено (дубли)
    assert storage.import_database(external) == 0

    storage.delete_saved(saved_id)
    assert storage.import_database(external) == 1

    # удаляем все оставшиеся записи
    for rec in storage.list_saved():
        storage.delete_saved(rec["id"])
    assert storage.list_saved() == []
    assert storage.get_saved(saved_id) is None


# --- черновик (draft): атомарное автосохранение и восстановление ------------ #
def test_draft_save_load_clear():
    payload = {
        "year": 2026, "month": 11, "manual": True, "department": "УПО",
        "employees": [{"name": "Иванов И.И.", "position": "вр.пед.уч.",
                       "rate": 1.0, "week_norm": 39, "days": {"2": "8-15,48"}}],
    }
    storage.save_draft(payload)
    assert storage.load_draft() == payload

    info = storage.draft_info()
    assert info["exists"] is True
    assert info["year"] == 2026
    assert info["month"] == 11
    assert info["employee_count"] == 1
    assert info["department"] == "УПО"

    storage.clear_draft()
    assert storage.load_draft() is None
    assert storage.draft_info()["exists"] is False


def test_draft_load_missing_and_corrupt():
    storage.clear_draft()
    assert storage.load_draft() is None
    # битый JSON не должен ронять загрузку
    draft_path = os.path.join(_TMP, "draft.json")
    with open(draft_path, "w", encoding="utf-8") as f:
        f.write("{ not valid json")
    assert storage.load_draft() is None
    assert storage.draft_info()["exists"] is False
    storage.clear_draft()
