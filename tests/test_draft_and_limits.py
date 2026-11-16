# -*- coding: utf-8 -*-
"""Тесты надёжности данных: черновик, лимит размера загрузки, автосохранение.

Проверяем:
  * ``GET /api/draft`` — сводка о черновике (нет черновика → exists=False);
  * ``POST /api/draft/restore`` — восстановление черновика в сессию (404 без него);
  * ``DELETE /api/draft`` — очистка;
  * автосохранение: правка ячейки пишет черновик (не теряем работу);
  * лимит размера загружаемого файла (MAX_UPLOAD_BYTES).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import app.main as main
from app.core import storage


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDROSTER_DATA_DIR", str(tmp_path))
    # чистим in-memory сессии между тестами
    main._sessions.clear()
    storage.clear_draft()
    yield
    main._sessions.clear()
    storage.clear_draft()


def test_draft_info_empty():
    resp = main.draft_info()
    assert resp.status_code == 200
    assert resp.body is not None
    import json
    data = json.loads(resp.body.decode("utf-8"))
    assert data["exists"] is False


def test_draft_restore_without_draft():
    resp = main.draft_restore()
    assert resp.status_code == 404


def test_draft_clear():
    resp = main.draft_clear()
    assert resp.status_code == 200


def test_cell_edit_autosaves_draft():
    # создаём график и добавляем сотрудника
    resp = main.create_schedule(year=2026, month=11)
    import json
    data = json.loads(resp.body.decode("utf-8"))
    sid = data["session_id"]

    resp = main.add_employee(sid, name="Иванов И.И.", position="вр.пед.уч.", rate=1.0,
                             week_norm=None)
    assert resp.status_code == 200
    data = json.loads(resp.body.decode("utf-8"))
    emp = data["employees"][0]
    idx = emp["index"]

    # правка ячейки → должен появиться черновик
    resp = main.edit_cell(sid, row_index=idx, day=2, value="8-15,48")
    assert resp.status_code == 200

    draft = storage.load_draft()
    assert draft is not None
    assert draft["employees"][0]["name"] == "Иванов И.И."
    assert draft["employees"][0]["days"].get("2") == "8-15,48"


def test_save_month_clears_draft():
    resp = main.create_schedule(year=2026, month=11)
    import json
    data = json.loads(resp.body.decode("utf-8"))
    sid = data["session_id"]
    main.add_employee(sid, name="Иванов И.И.", position="вр.пед.уч.", rate=1.0,
                      week_norm=None)
    data = json.loads(main._refresh_session(sid).body.decode("utf-8"))
    main.edit_cell(sid, row_index=0, day=2, value="8-15,48")
    assert storage.load_draft() is not None

    # сохранение месяца очищает черновик
    resp = main.save_schedule(sid, org="ГУЗ", dept="УПО", title="")
    assert resp.status_code == 200
    assert storage.load_draft() is None


def test_import_size_limit():
    # файл больше лимита должен вернуть 413
    big = b"0" * (main.MAX_UPLOAD_BYTES + 1)

    class FakeUpload:
        filename = "big.xls"

        async def read(self):
            return big

    import asyncio
    resp = asyncio.run(main.import_file(FakeUpload()))
    assert resp.status_code == 413


def test_database_import_size_limit():
    big = b"0" * (main.MAX_UPLOAD_BYTES + 1)

    class FakeUpload:
        filename = "big.db"

        async def read(self):
            return big

    import asyncio
    resp = asyncio.run(main.import_database_route(FakeUpload()))
    assert resp.status_code == 413
