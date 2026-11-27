# -*- coding: utf-8 -*-
"""Аудит HTTP-запросов к API: очередь в памяти + фоновая запись в SQLite.

Логируется каждый запрос к ``/api/*`` (в т.ч. не прошедшие авторизацию и
отклонённые по лимиту частоты): время, метод, путь, HTTP-статус, IP клиента,
результат авторизации и каким ключом (чьим тенантом) выполнялся запрос.

Записи копятся в неблокирующей очереди и пишутся в БД фоновым потоком
пачками — запись аудита не замедляет обработку запросов (важно на слабом
железе). Чтение — :func:`recent`, :func:`stats`, очистка — :func:`clear`.

Политика удержания: записи старше ``MEDROSTER_AUDIT_RETENTION_DAYS`` дней
(по умолчанию 90) удаляются при записи.
"""
from __future__ import annotations

import atexit
import queue
import threading
import time
from typing import Dict, List, Optional

from app.core import config, storage

# Максимум записей в очереди: защита памяти, если БД не справляется
# (в норме очередь опустошается за доли секунды).
_MAX_QUEUE = 10000


class AuditLog:
    """Очередь аудита + поток-писатель (один экземпляр на процесс)."""

    def __init__(self, flush_interval: float = 2.0, batch: int = 50) -> None:
        self._q: "queue.Queue[Dict]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._thread_lock = threading.Lock()
        self._stop = threading.Event()
        self._pending = 0              # записей, ожидающих записи в БД
        self._pending_lock = threading.Lock()
        self._flush_interval = flush_interval
        self._batch = batch
        self._prune_counter = 0        # каждые ~500 записей — подчистка старицы
        self._atexit_registered = False
        self._stopped = False

    # ------------------------------------------------------------------ #
    #  Публичный интерфейс
    # ------------------------------------------------------------------ #
    def log(self, entry: Dict) -> None:
        """Добавить запись аудита (неблокирующе; ничего не делает при отключённом аудите).

        ``entry``: {ts, method, path, status, client_ip, api_key_id, tenant,
        auth_status, duration_ms}.
        """
        if not config.AUDIT_ENABLED:
            return
        if self._stopped:
            return
        entry = dict(entry)
        entry.setdefault("ts", time.time())
        with self._pending_lock:
            self._pending += 1
        try:
            self._q.put_nowait(entry)
        except queue.Full:  # практический недостижимо (Queue не ограничена)
            with self._pending_lock:
                self._pending -= 1
            return
        # Защита от бесконтрольного роста, если писатель не успевает.
        if self._q.qsize() > _MAX_QUEUE:
            try:
                self._q.get_nowait()
                with self._pending_lock:
                    self._pending -= 1
            except queue.Empty:
                pass
        self._ensure_thread()

    def flush(self, timeout: float = 5.0) -> None:
        """Дождаться записи всех накопленных записей (тесты, остановка)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._pending_lock:
                pending = self._pending
            if pending <= 0:
                # даём потоку мгновение закрыть текущую транзакцию
                time.sleep(0.02)
                with self._pending_lock:
                    if self._pending <= 0:
                        return
            time.sleep(0.01)

    def stop(self) -> None:
        """Остановить поток и сбросить остатки очереди в БД."""
        self._stopped = True
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(2.0, self._flush_interval + 1.0))
        self._drain_sync()

    def recent(self, limit: int = 100, auth_status: Optional[str] = None,
               api_key_id: Optional[int] = None) -> List[Dict]:
        """Последние записи аудита (новые сверху)."""
        if limit <= 0 or limit > 1000:
            limit = 100
        clauses = []
        params: List = []
        if auth_status:
            clauses.append("auth_status = ?")
            params.append(auth_status)
        if api_key_id is not None:
            clauses.append("api_key_id = ?")
            params.append(int(api_key_id))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = storage.get_connection()
        try:
            rows = conn.execute(
                "SELECT id, ts, method, path, status, client_ip, api_key_id, "
                "       tenant, auth_status, duration_ms "
                "FROM api_audit_log%s ORDER BY id DESC LIMIT ?" % where,
                params + [int(limit)]).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def export_rows(self, auth_status: Optional[str] = None,
                    api_key_id: Optional[int] = None) -> List[Dict]:
        """Все записи аудита без лимита (для выгрузки в CSV), новые сверху.

        В отличие от ``recent`` не ограничена 1000 записей: объём журнала
        ограничивает retention (``MEDROSTER_AUDIT_RETENTION_DAYS``).
        """
        clauses = []
        params: List = []
        if auth_status:
            clauses.append("auth_status = ?")
            params.append(auth_status)
        if api_key_id is not None:
            clauses.append("api_key_id = ?")
            params.append(int(api_key_id))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = storage.get_connection()
        try:
            rows = conn.execute(
                "SELECT id, ts, method, path, status, client_ip, api_key_id, "
                "       tenant, auth_status, duration_ms "
                "FROM api_audit_log%s ORDER BY id DESC" % where,
                params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def stats(self) -> Dict:
        """Сводка: счётчики по результатам авторизации и топ тенантов."""
        conn = storage.get_connection()
        try:
            by_status = {r["auth_status"]: int(r["cnt"])
                         for r in conn.execute(
                             "SELECT auth_status, COUNT(*) AS cnt FROM api_audit_log "
                             "GROUP BY auth_status").fetchall()}
            by_tenant = [{"tenant": r["tenant"], "requests": int(r["cnt"])}
                         for r in conn.execute(
                             "SELECT tenant, COUNT(*) AS cnt FROM api_audit_log "
                             "WHERE tenant IS NOT NULL AND tenant != '' "
                             "GROUP BY tenant ORDER BY cnt DESC LIMIT 10").fetchall()]
            span = conn.execute(
                "SELECT MIN(ts) AS first, MAX(ts) AS last, COUNT(*) AS total "
                "FROM api_audit_log").fetchone()
            return {
                "total": int(span["total"] or 0),
                "first": span["first"],
                "last": span["last"],
                "by_status": by_status,
                "by_tenant": by_tenant,
            }
        finally:
            conn.close()

    def clear(self, older_than_days: Optional[int] = None) -> int:
        """Удалить записи аудита (все или старше N дней). Возвращает число удалённых."""
        conn = storage.get_connection()
        try:
            if older_than_days is None:
                cur = conn.execute("DELETE FROM api_audit_log")
            else:
                cutoff = time.time() - float(older_than_days) * 86400.0
                cur = conn.execute(
                    "DELETE FROM api_audit_log WHERE ts < ?", (cutoff,))
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def set_rate_limiter(self, limiter) -> None:
        """Связать с rate limiter для периодической чистки его счётчиков."""
        self._rate_limiter = limiter

    # ------------------------------------------------------------------ #
    #  Внутреннее
    # ------------------------------------------------------------------ #
    _rate_limiter = None

    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            if self._stopped:
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="med-roster-audit")
            self._thread.start()
            if not self._atexit_registered:
                atexit.register(self.stop)
                self._atexit_registered = True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=self._flush_interval)
            except queue.Empty:
                # заодно периодически чистим счётчики rate limiter
                limiter = self._rate_limiter
                if limiter is not None:
                    limiter.cleanup(max_age=300.0)
                continue
            entries = [item]
            while len(entries) < self._batch:
                try:
                    entries.append(self._q.get_nowait())
                except queue.Empty:
                    break
            self._write(entries)

    def _drain_sync(self) -> None:
        """Синхронно записать остатки очереди (остановка/тесты)."""
        entries = []
        while True:
            try:
                entries.append(self._q.get_nowait())
            except queue.Empty:
                break
        if entries:
            self._write(entries)

    def _write(self, entries: List[Dict]) -> None:
        try:
            conn = storage.get_connection()
            try:
                conn.executemany(
                    "INSERT INTO api_audit_log (ts, method, path, status, client_ip, "
                    "                           api_key_id, tenant, auth_status, "
                    "                           duration_ms) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(e.get("ts"), e.get("method"), e.get("path"), e.get("status"),
                      e.get("client_ip"), e.get("api_key_id"), e.get("tenant"),
                      e.get("auth_status"), e.get("duration_ms")) for e in entries])
                # статистика использования ключей
                for e in entries:
                    key_id = e.get("api_key_id")
                    if key_id:
                        conn.execute(
                            "UPDATE api_keys SET last_used_at=?, "
                            "       request_count=request_count+1 WHERE id=?",
                            (e.get("ts"), int(key_id)))
                # периодическая подчистка старых записей
                self._prune_counter += len(entries)
                if self._prune_counter >= 500:
                    self._prune_counter = 0
                    retention_days = max(1, int(config.AUDIT_RETENTION_DAYS))
                    cutoff = time.time() - retention_days * 86400.0
                    conn.execute("DELETE FROM api_audit_log WHERE ts < ?", (cutoff,))
                conn.commit()
            finally:
                conn.close()
        except Exception:
            # аудит не должен ломать обслуживание: silently drop
            # (записи теряются только при отказе диска/БД)
            pass
        finally:
            with self._pending_lock:
                self._pending -= len(entries)
                if self._pending < 0:
                    self._pending = 0
