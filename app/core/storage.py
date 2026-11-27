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

Кроме сохранённых месяцев БД хранит (с 0.10.0) интеграционные таблицы:
``tenants`` (клиники/МИС), ``api_keys`` (API-ключи, только SHA-256 хэши) и
``api_audit_log`` (аудит запросов) — см. ``app/core/api_auth.py`` и
``app/core/audit.py``.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
from typing import Dict, List, Optional, Tuple

from app.core import config

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


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Создать все таблицы, если их ещё нет (идемпотентно, с миграциями).

    Таблицы:
      * ``saved_months`` — сохранённые месяцы (JSON-блоб графика);
      * ``tenants``      — тенанты (клиники/МИС) для API-ключей;
      * ``api_keys``     — API-ключи (SHA-256 хэш + префикс, без секретов);
      * ``api_audit_log``— аудит HTTP-запросов к API.
    """
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
    if "department" not in cols:
        # 0.12.0: подразделение вынесено в колонку (идемпотентность push/pull
        # и фильтр find_saved по отделению). Существующие записи наполняем
        # из JSON-блоба data (однократно, в момент миграции).
        conn.execute(
            "ALTER TABLE saved_months ADD COLUMN department TEXT NOT NULL DEFAULT ''")
        for r in conn.execute("SELECT id, data FROM saved_months").fetchall():
            try:
                dept = (json.loads(r["data"]).get("department") or "").strip()
            except (TypeError, ValueError):
                dept = ""
            if dept:
                conn.execute(
                    "UPDATE saved_months SET department=? WHERE id=?", (dept, r["id"]))

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tenants (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL UNIQUE,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id     INTEGER NOT NULL,
            key_hash      TEXT NOT NULL UNIQUE,
            key_prefix    TEXT NOT NULL,
            label         TEXT NOT NULL DEFAULT '',
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    REAL NOT NULL,
            last_used_at  REAL,
            request_count INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)")
    key_cols = [r[1] for r in conn.execute("PRAGMA table_info(api_keys)").fetchall()]
    if "scopes" not in key_cols:
        # 0.12.0: права ключа (JSON-список "read"/"write"). Существующие ключи
        # получают полные права — поведение не меняется (обратная совместимость).
        conn.execute(
            "ALTER TABLE api_keys ADD COLUMN scopes TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          REAL NOT NULL,
            method      TEXT NOT NULL,
            path        TEXT NOT NULL,
            status      INTEGER NOT NULL,
            client_ip   TEXT,
            api_key_id  INTEGER,
            tenant      TEXT,
            auth_status TEXT NOT NULL,
            duration_ms REAL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_api_audit_log_ts ON api_audit_log(ts)")

    # Вебхуки: МИС регистрирует URL для уведомлений об изменениях графиков.
    # ``events`` — JSON-список строк; ``secret`` — HMAC-ключ доставки
    # (генерируется сервером, показывается один раз, как API-ключ).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS webhooks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id    INTEGER NOT NULL,
            url          TEXT NOT NULL,
            secret       TEXT NOT NULL,
            events       TEXT NOT NULL DEFAULT '[]',
            is_active    INTEGER NOT NULL DEFAULT 1,
            created_at   REAL NOT NULL,
            last_sent_at REAL,
            last_status  INTEGER,
            fail_count   INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_webhooks_tenant ON webhooks(tenant_id)")

    # Простое key-value хранилище настроек (например, секрет подписи экспорта).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    # 0.12.0: история доставок вебхуков — что, когда и с каким результатом
    # отправлено; используется для повтора (replay) пропущенных уведомлений.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS webhook_deliveries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            webhook_id  INTEGER NOT NULL,
            delivery_id TEXT NOT NULL,
            event       TEXT NOT NULL,
            subject     TEXT NOT NULL DEFAULT '',
            payload     TEXT NOT NULL,
            status      INTEGER,
            ok          INTEGER NOT NULL DEFAULT 0,
            attempts    INTEGER NOT NULL DEFAULT 0,
            created_at  REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_wd_webhook ON webhook_deliveries(webhook_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_wd_created ON webhook_deliveries(created_at)")


def init_db() -> None:
    """Создать таблицы, если их ещё нет (идемпотентно, с миграциями)."""
    with _connect() as conn:
        _ensure_schema(conn)


def get_connection() -> sqlite3.Connection:
    """Открыть соединение с гарантированно созданной схемой.

    Для фонового потока аудита и модулей api_auth/audit. Соединение нужно
    закрыть вызывающим кодом. Каталог данных читается при каждом вызове
    (``MEDROSTER_DATA_DIR``), поэтому смена env-переменной действует сразу —
    это используется тестами.
    """
    conn = _connect()
    try:
        _ensure_schema(conn)
    except Exception:
        conn.close()
        raise
    return conn


def save_month(year: int, month: int, org: str, payload: Dict,
               title: str = "", department: Optional[str] = None) -> Tuple[int, bool]:
    """Сохранить месяц (upsert) и вернуть ``(id, created)``.

    Запись уникальна по периоду и подразделению: повторное сохранение того же
    (год, месяц, отделение) обновляет существующую запись, а не создаёт копию.
    Это делает push от МИС идемпотентным (повтор запроса не плодит дубли) и
    убирает случайные дубли в списке сохранений UI. ``created=True`` — запись
    создана заново (событие ``month.saved``), ``False`` — заменена
    (``month.updated``).
    """
    if department is None:
        department = (payload.get("department") or "")
    department = (department or "").strip()
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM saved_months WHERE year=? AND month=? AND department=? "
            "ORDER BY id DESC LIMIT 1",
            (int(year), int(month), department)).fetchone()
        data = json.dumps(payload, ensure_ascii=False)
        if row is not None:
            conn.execute(
                "UPDATE saved_months SET org=?, source=?, data=?, saved_at=?, "
                "title=?, department=? WHERE id=?",
                (org or "", payload.get("source", ""), data, time.time(),
                 (title or "").strip(), department, int(row["id"])))
            return int(row["id"]), False
        cur = conn.execute(
            "INSERT INTO saved_months (year, month, org, source, data, saved_at, "
            "                           title, department) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (int(year), int(month), org or "", payload.get("source", ""),
             data, time.time(), (title or "").strip(), department),
        )
        return int(cur.lastrowid), True


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
            "SELECT id, year, month, org, source, saved_at, data, title, department "
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
            "dept": r["department"] or (data or {}).get("department", ""),
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


# --------------------------------------------------------------------------- #
#  Настройки (key-value): секрет подписи экспорта и другие служебные значения.
# --------------------------------------------------------------------------- #
def get_setting(key: str) -> Optional[str]:
    """Прочитать настройку; None, если не задана."""
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row is not None else None


def set_setting(key: str, value: str) -> None:
    """Сохранить настройку (upsert)."""
    init_db()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )


# --------------------------------------------------------------------------- #
#  Вебхуки (уведомления МИС об изменениях графиков).
# --------------------------------------------------------------------------- #
def create_webhook(tenant_id: int, url: str, secret: str,
                   events: List[str]) -> int:
    """Зарегистрировать вебхук; вернуть id."""
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO webhooks (tenant_id, url, secret, events, is_active, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (int(tenant_id), url, secret,
             json.dumps(list(events), ensure_ascii=False), time.time()))
        return int(cur.lastrowid)


def get_webhook(webhook_id: int) -> Optional[Dict]:
    """Вебхук по id (или None)."""
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM webhooks WHERE id=?", (webhook_id,)).fetchone()
    return _webhook_row_to_dict(row) if row is not None else None


def list_webhooks(tenant_id: Optional[int] = None) -> List[Dict]:
    """Список вебхуков (всех или одного тенанта), без секретов."""
    init_db()
    with _connect() as conn:
        if tenant_id is None:
            rows = conn.execute(
                "SELECT w.*, t.name AS tenant_name FROM webhooks w "
                "LEFT JOIN tenants t ON t.id = w.tenant_id "
                "ORDER BY w.id").fetchall()
        else:
            rows = conn.execute(
                "SELECT w.*, t.name AS tenant_name FROM webhooks w "
                "LEFT JOIN tenants t ON t.id = w.tenant_id "
                "WHERE w.tenant_id=? ORDER BY w.id", (int(tenant_id),)).fetchall()
    out = []
    for r in rows:
        d = _webhook_row_to_dict(r)
        d["tenant"] = r["tenant_name"] if "tenant_name" in r.keys() else ""
        out.append(d)
    return out


def _webhook_row_to_dict(row) -> Dict:
    """Вебхук в словарь (без секрета — только факт его наличия)."""
    try:
        events = json.loads(row["events"])
    except (TypeError, ValueError):
        events = []
    return {
        "id": row["id"],
        "tenant_id": row["tenant_id"],
        "url": row["url"],
        "events": events,
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "last_sent_at": row["last_sent_at"],
        "last_status": row["last_status"],
        "fail_count": row["fail_count"],
        "has_secret": bool(row["secret"]),
    }


def get_webhook_secret(webhook_id: int) -> Optional[str]:
    """Секрет доставки вебхука (нужен потоку отправки; наружу не отдаётся)."""
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT secret FROM webhooks WHERE id=?",
                           (webhook_id,)).fetchone()
    return row["secret"] if row is not None else None


def delete_webhook(webhook_id: int, tenant_id: Optional[int] = None) -> bool:
    """Удалить вебхук; True, если существовал. Тенант удаляет только свой."""
    init_db()
    with _connect() as conn:
        if tenant_id is None:
            cur = conn.execute("DELETE FROM webhooks WHERE id=?", (webhook_id,))
        else:
            cur = conn.execute("DELETE FROM webhooks WHERE id=? AND tenant_id=?",
                               (webhook_id, int(tenant_id)))
        return cur.rowcount > 0


def set_webhook_active(webhook_id: int, active: bool,
                       tenant_id: Optional[int] = None) -> bool:
    """Включить/отключить вебхук; True, если существовал."""
    init_db()
    with _connect() as conn:
        if tenant_id is None:
            cur = conn.execute("UPDATE webhooks SET is_active=? WHERE id=?",
                               (1 if active else 0, webhook_id))
        else:
            cur = conn.execute(
                "UPDATE webhooks SET is_active=? WHERE id=? AND tenant_id=?",
                (1 if active else 0, webhook_id, int(tenant_id)))
        return cur.rowcount > 0


def record_webhook_delivery(webhook_id: int, ok: bool, status: Optional[int],
                            event: str = "", subject: str = "", payload: str = "",
                            delivery_id: str = "", attempts: int = 0) -> None:
    """Зафиксировать результат доставки: счётчики вебхука + запись истории.

    История (``webhook_deliveries``) хранится ``WEBHOOK_DELIVERY_RETENTION_DAYS``
    дней и позволяет повторить неудачные доставки (replay).
    """
    init_db()
    now = time.time()
    with _connect() as conn:
        if ok:
            conn.execute(
                "UPDATE webhooks SET last_sent_at=?, last_status=?, fail_count=0 "
                "WHERE id=?", (now, status, webhook_id))
        else:
            conn.execute(
                "UPDATE webhooks SET last_sent_at=?, last_status=?, "
                "fail_count=fail_count+1 WHERE id=?",
                (now, status, webhook_id))
        if delivery_id:
            conn.execute(
                "INSERT INTO webhook_deliveries (webhook_id, delivery_id, event, "
                "                            subject, payload, status, ok, "
                "                            attempts, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (int(webhook_id), delivery_id, event or "", subject or "",
                 payload or "", status, 1 if ok else 0, int(attempts), now))
            retention = max(1, int(config.WEBHOOK_DELIVERY_RETENTION_DAYS))
            conn.execute("DELETE FROM webhook_deliveries WHERE created_at < ?",
                         (now - retention * 86400.0,))


def find_saved(year: int, month: int,
               department: Optional[str] = None) -> Optional[Dict]:
    """Последнее сохранение за период (полные данные) или None.

    ``department`` (необязательно) — фильтр по подразделению: в клинике может
    быть несколько графиков за один период (отделения). Без фильтра берётся
    самое свежее сохранение любого подразделения.
    """
    init_db()
    query = "SELECT id, data, department FROM saved_months WHERE year=? AND month=?"
    params: List = [int(year), int(month)]
    if department is not None:
        query += " AND department=?"
        params.append(department.strip())
    query += " ORDER BY id DESC LIMIT 1"
    with _connect() as conn:
        row = conn.execute(query, params).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "data": json.loads(row["data"]),
            "department": row["department"] or ""}


def list_webhook_deliveries(webhook_id: int, limit: int = 50,
                            only_failed: bool = False,
                            tenant_id: Optional[int] = None) -> List[Dict]:
    """История доставок вебхука (новые сверху), без тенанта — только свой."""
    init_db()
    limit = max(1, min(int(limit), 500))
    query = ("SELECT d.* FROM webhook_deliveries d "
             "JOIN webhooks w ON w.id = d.webhook_id "
             "WHERE d.webhook_id = ?")
    params: List = [int(webhook_id)]
    if only_failed:
        query += " AND d.ok = 0"
    if tenant_id is not None:
        query += " AND w.tenant_id = ?"
        params.append(int(tenant_id))
    query += " ORDER BY d.id DESC LIMIT ?"
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [{
        "id": r["id"],
        "webhook_id": r["webhook_id"],
        "delivery_id": r["delivery_id"],
        "event": r["event"],
        "subject": r["subject"],
        "status": r["status"],
        "ok": bool(r["ok"]),
        "attempts": r["attempts"],
        "created_at": r["created_at"],
    } for r in rows]


def get_webhook_delivery(delivery_id: str,
                         tenant_id: Optional[int] = None) -> Optional[Dict]:
    """Одна запись истории доставок (для replay конкретной доставки)."""
    init_db()
    query = ("SELECT d.*, w.tenant_id AS wh_tenant FROM webhook_deliveries d "
             "JOIN webhooks w ON w.id = d.webhook_id "
             "WHERE d.delivery_id = ?")
    params: List = [str(delivery_id)]
    if tenant_id is not None:
        query += " AND w.tenant_id = ?"
        params.append(int(tenant_id))
    with _connect() as conn:
        row = conn.execute(query, params).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "webhook_id": row["webhook_id"],
        "delivery_id": row["delivery_id"],
        "event": row["event"],
        "subject": row["subject"],
        "payload": row["payload"],
        "status": row["status"],
        "ok": bool(row["ok"]),
        "attempts": row["attempts"],
        "created_at": row["created_at"],
    }
