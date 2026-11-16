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
import sys
import tempfile
import time
from typing import Dict, List, Optional

_DB_FILENAME = "med-roster.db"

# Файл черновика (несохранённый график текущей сессии). Восстанавливается при
# запуске, чтобы пользователь не потерял работу после закрытия/сбоя программы.
_DRAFT_FILENAME = "draft.json"


def get_data_dir() -> str:
    """Каталог данных (создаётся по требованию).

    В portable / установленной сборке данные лежат рядом с программой, чтобы
    базу можно было переносить вместе с папкой. При запуске из исходников —
    каталог данных пользователя.
    """
    env = os.environ.get("MEDROSTER_DATA_DIR")
    if env:
        return env
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
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
    """Создать таблицу, если её ещё нет (идемпотентно, с миграциями)."""
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
        cols = [r[1] for r in conn.execute("PRAGMA table_info(saved_months)").fetchall()]
        if "title" not in cols:
            conn.execute("ALTER TABLE saved_months ADD COLUMN title TEXT NOT NULL DEFAULT ''")


def save_month(year: int, month: int, org: str, payload: Dict,
               title: str = "") -> int:
    """Сохранить месяц, вернуть id записи."""
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO saved_months (year, month, org, source, data, saved_at, title) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (int(year), int(month), org or "", payload.get("source", ""),
             json.dumps(payload, ensure_ascii=False), time.time(),
             (title or "").strip()),
        )
        return int(cur.lastrowid)


def rename_saved(saved_id: int, title: str) -> bool:
    """Переименовать сохранённый месяц; True, если запись существовала."""
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE saved_months SET title=? WHERE id=?",
            ((title or "").strip(), int(saved_id)))
        return cur.rowcount > 0


def update_saved(saved_id: int, org: str, dept: str, payload: Dict) -> bool:
    """Обновить данные сохранённого месяца; True, если запись существовала."""
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE saved_months SET org=?, data=?, saved_at=? WHERE id=?",
            (org or "", json.dumps(payload, ensure_ascii=False), time.time(), int(saved_id)))
        return cur.rowcount > 0


def list_saved() -> List[Dict]:
    """Список сохранённых месяцев (сводки, без полных данных)."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, year, month, org, source, saved_at, data, title "
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
            "dept": (data or {}).get("department", ""),
            "source": r["source"],
            "saved_at": r["saved_at"],
            "title": r["title"],
            "employee_count": len((data or {}).get("employees", [])),
        })
    return out


def export_database() -> str:
    """Вернуть путь к файлу БД (для копирования базы в выбранное место)."""
    init_db()
    return _db_path()


def import_database(source_path: str) -> int:
    """Импортировать записи из сторонней базы ``med-roster.db``.

    Возвращает число добавленных записей. Файл проверяется: должен содержать
    таблицу ``saved_months`` с нужными колонками. Существующие записи
    локальной базы сохраняются (объединение по содержимому).
    """
    init_db()
    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    try:
        cols = [r[1] for r in source.execute("PRAGMA table_info(saved_months)").fetchall()]
        required = {"year", "month", "org", "source", "data"}
        if not required.issubset(set(cols)):
            raise ValueError("Файл не является базой med-roster (нет таблицы saved_months)")

        title_in = "title" in cols
        if title_in:
            rows = source.execute(
                "SELECT year, month, org, source, data, saved_at, title FROM saved_months").fetchall()
        else:
            rows = source.execute(
                "SELECT year, month, org, source, data, saved_at FROM saved_months").fetchall()
    finally:
        source.close()

    local = _connect()
    try:
        existing = set()
        for r in local.execute("SELECT year, month, data FROM saved_months").fetchall():
            try:
                d = json.loads(r["data"])
            except ValueError:
                d = r["data"]
            existing.add((r["year"], r["month"], json.dumps(d, sort_keys=True, ensure_ascii=False)))

        added = 0
        for row in rows:
            try:
                data = json.loads(row["data"])
            except ValueError:
                data = row["data"]
            key = (row["year"], row["month"],
                   json.dumps(data, sort_keys=True, ensure_ascii=False))
            if key in existing:
                continue
            title = row["title"] if title_in else ""
            local.execute(
                "INSERT INTO saved_months (year, month, org, source, data, saved_at, title) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (int(row["year"]), int(row["month"]), row["org"] or "",
                 row["source"] or "", json.dumps(data, ensure_ascii=False),
                 float(row["saved_at"] or 0.0), (title or "").strip()))
            existing.add(key)
            added += 1
        local.commit()
        return added
    finally:
        local.close()


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


# --------------------------------------------------------------------------- #
#  Черновик (draft): автосохранение текущей сессии без участия пользователя.
#
#  Отличие от «сохранённых месяцев»: черновик пишется автоматически при каждом
#  изменении графика и переживает перезапуск программы. Это страховка от потери
#  несохранённой работы (закрытие вкладки, сбой, отключение питания).
# --------------------------------------------------------------------------- #
def _draft_path() -> str:
    return os.path.join(get_data_dir(), _DRAFT_FILENAME)


def save_draft(payload: Dict) -> None:
    """Атомарно сохранить черновик (запись во временный файл + rename).

    Запись во временный файл и последующий ``os.replace`` гарантируют, что при
    сбое в середине записи на диске не останется «половинчатого» JSON — либо
    старый черновик, либо новый, но никогда не битый.
    """
    os.makedirs(get_data_dir(), exist_ok=True)
    path = _draft_path()
    fd, tmp_path = tempfile.mkstemp(prefix=".draft-", suffix=".tmp",
                                    dir=get_data_dir())
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        # не оставляем временный файл при любой ошибке
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def load_draft() -> Optional[Dict]:
    """Загрузить черновик, если он есть и не повреждён.

    Возвращает ``None``, если файла нет или он не читается/битый. Битый черновик
    не должен ломать запуск программы — просто игнорируем его.
    """
    path = _draft_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except (OSError, ValueError):
        return None


def clear_draft() -> None:
    """Удалить черновик (после сохранения месяца или по явной команде)."""
    try:
        os.remove(_draft_path())
    except OSError:
        pass


def draft_info() -> Dict:
    """Сводка о черновике: есть ли он, период, число сотрудников, время записи."""
    data = load_draft()
    if data is None:
        return {"exists": False}
    try:
        mtime = os.path.getmtime(_draft_path())
    except OSError:
        mtime = 0.0
    return {
        "exists": True,
        "year": data.get("year"),
        "month": data.get("month"),
        "manual": bool(data.get("manual", False)),
        "department": data.get("department", "") or "",
        "employee_count": len(data.get("employees", []) or []),
        "saved_at": mtime,
    }
