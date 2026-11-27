# -*- coding: utf-8 -*-
"""API-ключи и тенанты (подразделения/клиники) для интеграции с внешними системами (МИС).

Модель доступа (Фаза 1):
* один ключ = один тенант (клиника/МИС) с полными правами на данные API;
* роли и гранулярные права — в следующих фазах;
* управление ключами (создание/отзыв) — только с локального компьютера
  (см. middleware в ``app/main.py``).

Формат ключа: ``mrk_`` + 40 hex-символов (128 бит энтропии).
В базе хранится только SHA-256 хэш ключа и человекочитаемый префикс
(первые 12 символов) — полный ключ показывается ровно один раз при создании.

Таблицы ``tenants`` / ``api_keys`` / ``api_audit_log`` создаются в
``app.core.storage.init_db``.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from typing import Dict, List, Optional

from app.core import storage

# Формат ключа: mrk_<40 hex>
KEY_MARKER = "mrk_"
_KEY_RANDOM_BYTES = 20  # 20 байт → 40 hex-символов
_DISPLAY_PREFIX_LEN = 12  # сколько символов показывать в списке ключей

# Кэш факта «есть ли активные ключи» — проверяется на каждый анонимный запрос,
# поэтому обновляем не чаще раза в 30 секунд и сбрасываем при изменениях.
_HAS_KEYS_CACHE_TTL = 30.0
_has_keys_cache: Optional[bool] = None
_has_keys_cached_at = 0.0


# --------------------------------------------------------------------------- #
#  Генерация и хэширование
# --------------------------------------------------------------------------- #
def generate_key() -> str:
    """Сгенерировать новый случайный ключ (полная секретная строка)."""
    return KEY_MARKER + secrets.token_hex(_KEY_RANDOM_BYTES)


def _hash_key(key: str) -> str:
    """SHA-256 hex ключа — то, что хранится в БД."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _display_prefix(key: str) -> str:
    return key[:_DISPLAY_PREFIX_LEN]


# --------------------------------------------------------------------------- #
#  Тенанты
# --------------------------------------------------------------------------- #
def ensure_tenant(name: str) -> int:
    """Найти тенант по имени или создать; вернуть его id."""
    name = (name or "").strip()
    if not name:
        raise ValueError("укажите название тенанта (клиники/МИС)")
    conn = storage.get_connection()
    try:
        row = conn.execute("SELECT id FROM tenants WHERE name=?", (name,)).fetchone()
        if row is not None:
            return int(row["id"])
        cur = conn.execute(
            "INSERT INTO tenants (name, created_at) VALUES (?, ?)",
            (name, time.time()))
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_tenants() -> List[Dict]:
    """Список тенантов с числом активных ключей."""
    conn = storage.get_connection()
    try:
        rows = conn.execute(
            "SELECT t.id, t.name, t.created_at, "
            "       (SELECT COUNT(*) FROM api_keys k "
            "        WHERE k.tenant_id = t.id AND k.is_active = 1) AS active_keys "
            "FROM tenants t ORDER BY t.name").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
#  CRUD ключей
# --------------------------------------------------------------------------- #
def create_key(tenant: str, label: str = "") -> Dict:
    """Создать новый API-ключ для тенанта.

    Возвращает словарь с полным ключом (``key``) — он показывается пользователю
    ровно один раз; восстановить его нельзя, только перевыпустить.
    """
    tenant_id = ensure_tenant(tenant)
    label = (label or "").strip()
    key = generate_key()
    conn = storage.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO api_keys (tenant_id, key_hash, key_prefix, label, "
            "                      is_active, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (tenant_id, _hash_key(key), _display_prefix(key), label, time.time()))
        conn.commit()
        key_id = int(cur.lastrowid)
    finally:
        conn.close()
    _invalidate_has_keys_cache()
    return {
        "id": key_id,
        "tenant": (tenant or "").strip(),
        "label": label,
        "key": key,          # единственный раз в открытом виде
        "prefix": _display_prefix(key),
    }


def list_keys() -> List[Dict]:
    """Список ключей (без секретов: только префиксы и метаданные)."""
    conn = storage.get_connection()
    try:
        rows = conn.execute(
            "SELECT k.id, k.key_prefix, k.label, k.is_active, k.created_at, "
            "       k.last_used_at, k.request_count, t.name AS tenant "
            "FROM api_keys k JOIN tenants t ON t.id = k.tenant_id "
            "ORDER BY k.is_active DESC, k.id DESC").fetchall()
        out = []
        for r in rows:
            out.append({
                "id": int(r["id"]),
                "prefix": r["key_prefix"],
                "label": r["label"] or "",
                "tenant": r["tenant"],
                "is_active": bool(r["is_active"]),
                "created_at": r["created_at"],
                "last_used_at": r["last_used_at"],
                "request_count": int(r["request_count"] or 0),
            })
        return out
    finally:
        conn.close()


def revoke_key(key_id: int) -> bool:
    """Отключить ключ (is_active=0). История аудита сохраняется."""
    conn = storage.get_connection()
    try:
        cur = conn.execute("UPDATE api_keys SET is_active=0 WHERE id=?", (int(key_id),))
        conn.commit()
        ok = cur.rowcount > 0
    finally:
        conn.close()
    _invalidate_has_keys_cache()
    return ok


def activate_key(key_id: int) -> bool:
    """Включить ранее отозванный ключ."""
    conn = storage.get_connection()
    try:
        cur = conn.execute("UPDATE api_keys SET is_active=1 WHERE id=?", (int(key_id),))
        conn.commit()
        ok = cur.rowcount > 0
    finally:
        conn.close()
    _invalidate_has_keys_cache()
    return ok


def delete_key(key_id: int) -> bool:
    """Удалить ключ полностью (вместе со статистикой; аудит остаётся).

    Обычно достаточно :func:`revoke_key` — она обратима.
    """
    conn = storage.get_connection()
    try:
        cur = conn.execute("DELETE FROM api_keys WHERE id=?", (int(key_id),))
        conn.commit()
        ok = cur.rowcount > 0
    finally:
        conn.close()
    _invalidate_has_keys_cache()
    return ok


# --------------------------------------------------------------------------- #
#  Проверка ключей
# --------------------------------------------------------------------------- #
def verify_key(key: str) -> Optional[Dict]:
    """Проверить ключ → метаданные тенанта или None (ключ неверный/отозван)."""
    key = (key or "").strip()
    if not key.startswith(KEY_MARKER):
        return None
    key_hash = _hash_key(key)
    conn = storage.get_connection()
    try:
        row = conn.execute(
            "SELECT k.id, k.label, k.is_active, t.name AS tenant "
            "FROM api_keys k JOIN tenants t ON t.id = k.tenant_id "
            "WHERE k.key_hash = ?", (key_hash,)).fetchone()
    finally:
        conn.close()
    if row is None or not row["is_active"]:
        return None
    return {
        "id": int(row["id"]),
        "tenant": row["tenant"],
        "label": row["label"] or "",
    }


def has_active_keys() -> bool:
    """Есть ли хоть один активный ключ (с кэшем на 30 секунд).

    Опрашивается на каждый запрос без ключа от внешнего клиента: если ключи
    настроены — внешний анонимный доступ закрывается; если нет — сервер
    продолжает работать в прежнем «открытом» режиме (обратная совместимость).
    """
    global _has_keys_cache, _has_keys_cached_at
    now = time.time()
    if _has_keys_cache is not None and now - _has_keys_cached_at < _HAS_KEYS_CACHE_TTL:
        return _has_keys_cache
    conn = storage.get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM api_keys WHERE is_active=1 LIMIT 1").fetchone()
        result = row is not None
    finally:
        conn.close()
    _has_keys_cache = result
    _has_keys_cached_at = now
    return result


def _invalidate_has_keys_cache() -> None:
    """Сбросить кэш has_active_keys (вызывается при изменении ключей)."""
    global _has_keys_cache, _has_keys_cached_at
    _has_keys_cache = None
    _has_keys_cached_at = 0.0


def reset_cache() -> None:
    """Публичный сброс кэша (используется тестами при смене каталога данных)."""
    _invalidate_has_keys_cache()
