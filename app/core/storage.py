# -*- coding: utf-8 -*-
"""
Локальное хранилище сохранённых графиков (SQLite, только stdlib).

Назначение: сохранять импортированный или заполненный вручную месяц, чтобы
позже загрузить его и сгенерировать на его основе следующие месяцы.

Расположение файла БД (``med-roster.db``) — в папке данных пользователя:
  * Windows  — ``%APPDATA%\\med-roster``;
  * Linux    — ``~/.local/share/med-roster`` (или ``$XDG_DATA_HOME/med-roster``);
  * переопределение — переменная окружения ``MEDROSTER_DATA_DIR``.

Данные хранятся как JSON-блоб (результат ``serialize_result`` из
``app.services.xls_importer``), поэтому восстановление идёт через
``deserialize_result``.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Dict, List, Optional

_DB_FILENAME = "med-roster.db"


def get_data_dir() -> str:
    """Каталог данных пользователя (создаётся по требованию)."""
    env = os.environ.get("MEDROSTER_DATA_DIR")
    if env:
        return env
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "med-roster")
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "med-roster")


def _db_path() -> str:
    return os.path.join(get_data_dir(), _DB_FILENAME)


def _connect() -> sqlite3.Connection:
    os.makedirs(get_data_dir(), exist_ok=True)
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Создать таблицу, если её ещё нет (идемпотентно)."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_months (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                year     INTEGER NOT NULL,
                month    INTEGER NOT NULL,
                org      TEXT NOT NULL DEFAULT '',
                source   TEXT NOT NULL DEFAULT '',
                data     TEXT NOT NULL,
                saved_at REAL NOT NULL
            )
            """
        )


def save_month(year: int, month: int, org: str, payload: Dict) -> int:
    """Сохранить месяц, вернуть id записи."""
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO saved_months (year, month, org, source, data, saved_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (int(year), int(month), org or "", payload.get("source", ""),
             json.dumps(payload, ensure_ascii=False), time.time()),
        )
        return int(cur.lastrowid)


def list_saved() -> List[Dict]:
    """Список сохранённых месяцев (сводки, без полных данных)."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, year, month, org, source, saved_at, data "
            "FROM saved_months ORDER BY year DESC, month DESC, id DESC"
        ).fetchall()
    out = []
    for r in rows:
        data = json.loads(r["data"])
        out.append({
            "id": r["id"],
            "year": r["year"],
            "month": r["month"],
            "org": r["org"],
            "source": r["source"],
            "saved_at": r["saved_at"],
            "employee_count": len((data or {}).get("employees", [])),
        })
    return out


def get_saved(saved_id: int) -> Optional[Dict]:
    """Вернуть полные данные сохранённого месяца (или None)."""
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT data FROM saved_months WHERE id=?", (saved_id,)).fetchone()
    if row is None:
        return None
    return json.loads(row["data"])


def delete_saved(saved_id: int) -> bool:
    """Удалить сохранённый месяц; True, если запись существовала."""
    init_db()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM saved_months WHERE id=?", (saved_id,))
        return cur.rowcount > 0
