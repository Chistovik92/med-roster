# -*- coding: utf-8 -*-
"""Вебхуки: уведомления МИС об изменениях графиков.

МИС регистрирует URL (эндпоинт управления — ``/api/webhooks``), и сервер
отправляет туда POST-запросы с JSON-сообщением при событиях:

* ``month.saved``     — месяц сохранён в базу (новая запись);
* ``month.updated``    — сохранённый месяц обновлён из сессии;
* ``month.deleted``    — сохранённый месяц удалён;
* ``schedule.changed`` — график в сессии изменился (правка ячейки, автозаполнение,
  копирование, генерация, добавление/изменение/удаление сотрудника);
* ``webhook.test``     — тестовая доставка (по команде, независимо от подписки).

Формат сообщения::

    {
      "event": "month.saved",
      "ts": 1764000000.0,
      "data": {"saved_id": 3, "year": 2026, "month": 11, ...}
    }

Заголовки запроса:

* ``X-MedRoster-Event``     — имя события;
* ``X-MedRoster-Signature`` — ``sha256=<hex>`` — HMAC-SHA256 тела запроса
  с секретом вебхука (секрет выдаётся при регистрации один раз);
* ``X-MedRoster-Delivery``  — уникальный id доставки (для идемпотентности).

Доставка асинхронная (фоновый поток), не блокирует HTTP-запросы. Быстрые
повторные события по одному объекту склеиваются: пока доставка ждёт в очереди,
новое событие того же типа по тому же объекту заменяет старое (актуально для
``schedule.changed`` при редактировании ячеек). После ``MAX_FAILURES`` неудач
подряд вебхук автоматически отключается (``is_active=0``).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Dict, List, Optional

from app.core import config, storage

KNOWN_EVENTS = ("month.saved", "month.updated", "month.deleted",
                "schedule.changed", "webhook.test")

# Число попыток доставки одного сообщения (1-я + повторы).
MAX_ATTEMPTS = 2
# Пауза между опросами очереди, сек.
_POLL_INTERVAL = 0.25

_lock = threading.Lock()
# Очередь доставок с коалесцингом: ключ (webhook_id, event, subject) -> элемент.
# Повторное событие по тому же ключу заменяет ждущее — получатель видит только
# самое свежее состояние.
_pending: Dict[tuple, Dict] = {}
_worker_started = False

# Точка подмены для тестов (monkeypatch webhooks._urlopen).
_urlopen = urllib.request.urlopen


def _ensure_worker() -> None:
    """Запустить фоновый поток доставки (лениво, при первом событии)."""
    global _worker_started
    if _worker_started:
        return
    _worker_started = True
    threading.Thread(target=_worker_loop, daemon=True,
                     name="medroster-webhooks").start()


def _worker_loop() -> None:
    while True:
        with _lock:
            batch = list(_pending.values())
            _pending.clear()
        for item in batch:
            try:
                _deliver(item)
            except Exception:  # noqa: BLE001 — поток не должен умирать
                pass
        time.sleep(_POLL_INTERVAL)


def _deliver(item: Dict) -> None:
    """Одна попытка доставки; при неудаче — повторная постановка в очередь."""
    webhook_id = item["webhook_id"]
    payload = item["payload"]
    secret = storage.get_webhook_secret(webhook_id)
    if secret is None:
        return  # вебхук удалён, пока ждал в очереди
    hook = storage.get_webhook(webhook_id)
    if hook is None or not hook["is_active"]:
        return

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), body,
                          hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        hook["url"], data=body, method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-MedRoster-Event": payload.get("event", ""),
            "X-MedRoster-Signature": "sha256=" + signature,
            "X-MedRoster-Delivery": item["delivery_id"],
            "User-Agent": "med-roster-webhook/1",
        })
    status: Optional[int] = None
    ok = False
    try:
        with _urlopen(req, timeout=config.WEBHOOK_TIMEOUT) as resp:
            status = int(resp.status)
            ok = 200 <= status < 300
    except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
        status = int(exc.code)
    except Exception:  # noqa: BLE001 — сеть, DNS, таймаут
        status = None

    storage.record_webhook_delivery(webhook_id, ok, status)

    # Автоотключение после серии неудач (если лимит включён).
    max_failures = config.WEBHOOK_MAX_FAILURES
    if max_failures and not ok:
        hook = storage.get_webhook(webhook_id)
        if hook is not None and hook["fail_count"] >= max_failures:
            storage.set_webhook_active(webhook_id, False)

    # Повторная попытка (одна), если доставка не удалась.
    if not ok and item["attempts"] < MAX_ATTEMPTS:
        retry = dict(item)
        retry["attempts"] = item["attempts"] + 1
        key = (webhook_id, payload.get("event", ""),
              payload.get("data", {}).get("subject", ""))
        with _lock:
            _pending[key] = retry
        _ensure_worker()


def emit_event(event: str, data: Dict,
               only_webhook_id: Optional[int] = None) -> int:
    """Уведомить подписчиков о событии; вернуть число адресатов.

    ``data`` может содержать ``subject`` — идентификатор объекта (id сохранения,
    id сессии); события по одному subject склеиваются в очереди.
    """
    if event not in KNOWN_EVENTS:
        raise ValueError("неизвестное событие: %r" % event)
    hooks: List[Dict] = storage.list_webhooks()
    if only_webhook_id is not None:
        # Явный адресат (тестовая доставка): подписка на событие не нужна.
        matching = [h for h in hooks
                    if h["id"] == only_webhook_id and h["is_active"]]
    else:
        matching = [h for h in hooks
                    if h["is_active"] and event in h["events"]]
    if not matching:
        return 0

    payload = {"event": event, "ts": time.time(), "data": data}
    subject = data.get("subject", "")
    for h in matching:
        key = (h["id"], event, subject)
        with _lock:
            _pending[key] = {
                "webhook_id": h["id"],
                "payload": payload,
                "attempts": 0,
                "delivery_id": uuid.uuid4().hex,
            }
    _ensure_worker()
    return len(matching)


def pending_count() -> int:
    """Сколько доставок ждёт в очереди (для тестов и диагностики)."""
    with _lock:
        return len(_pending)


def wait_delivered(timeout: float = 5.0) -> bool:
    """Дождаться, пока очередь опустеет (для тестов). True — опустела."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pending_count() == 0:
            # даём воркеру время обработать последнюю партию
            time.sleep(0.1)
            if pending_count() == 0:
                return True
        time.sleep(0.05)
    return pending_count() == 0


def reset() -> None:
    """Очистить очередь (для тестов)."""
    with _lock:
        _pending.clear()
