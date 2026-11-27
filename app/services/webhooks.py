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

Каждая доставка (итог всех попыток) пишется в историю — таблицу
``webhook_deliveries``: событие, payload, HTTP-статус, число попыток. История
видна через ``GET /api/webhooks/{id}/deliveries``, а неудачную доставку можно
повторить (``POST /api/webhooks/{id}/replay``) — МИС не пропустит уведомление,
даже если в момент доставки её сервер был недоступен.
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
# Пауза перед повторной попыткой доставки, сек (в тестах уменьшается).
RETRY_DELAY = 1.0
# Окно коалесцинга, сек: после первого события воркер выжидает столько,
# чтобы быстрые повторные события по тому же объекту успели заменить
# ждущие в очереди (правка ячеек -> одна доставка с самым свежим состоянием).
COALESCE_WINDOW = 0.25
# Максимальное ожидание воркера без событий (страховка); новые события
# будят воркера мгновенно через Condition.notify_all.
_IDLE_WAIT = 30.0

# Всё состояние очереди синхронизируется через _cond:
#   _pending — очередь с коалесцингом, ключ (webhook_id, event, subject);
#   _busy    — воркер обрабатывает взятую партию (для wait_delivered).
# Повторное событие по тому же ключу заменяет ждущее — получатель видит
# только самое свежее состояние.
_cond = threading.Condition()
_pending: Dict[tuple, Dict] = {}
_busy = False
_worker_started = False

# Точка подмены для тестов (monkeypatch webhooks._urlopen).
_urlopen = urllib.request.urlopen


def _ensure_worker() -> None:
    """Запустить фоновый поток доставки (лениво, при первом событии)."""
    global _worker_started
    with _cond:
        if _worker_started:
            return
        _worker_started = True
    threading.Thread(target=_worker_loop, daemon=True,
                     name="medroster-webhooks").start()


def _worker_loop() -> None:
    global _busy
    while True:
        batch: List[Dict] = []
        with _cond:
            # ждём первого события (notify от emit_event/retry или таймаут)
            while not _pending:
                _cond.wait(_IDLE_WAIT)
            # окно коалесцинга: повторные события по тому же объекту
            # успевают заменить ждущие (notify будит, но мы всё равно
            # дожидаемся конца окна и берём самое свежее состояние)
            _cond.wait(COALESCE_WINDOW)
            now = time.time()
            ready = [(k, v) for k, v in _pending.items()
                     if v.get("not_before", 0.0) <= now]
            for k, _ in ready:
                _pending.pop(k, None)
            batch = [v for _, v in ready]
            _busy = bool(batch)
        for item in batch:
            try:
                _deliver(item)
            except Exception:  # noqa: BLE001 — поток не должен умирать
                pass
        with _cond:
            _busy = False
            _cond.notify_all()


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

    attempts = int(item.get("attempts", 0)) + 1
    final = ok or attempts >= MAX_ATTEMPTS
    # Счётчики вебхука обновляются на каждую попытку; в историю доставка
    # попадает один раз — с итогом всех попыток.
    storage.record_webhook_delivery(
        webhook_id, ok, status,
        event=payload.get("event", ""),
        subject=payload.get("data", {}).get("subject", ""),
        payload=json.dumps(payload, ensure_ascii=False),
        delivery_id=item["delivery_id"] if final else "",
        attempts=attempts)

    # Автоотключение после серии неудач (если лимит включён).
    max_failures = config.WEBHOOK_MAX_FAILURES
    if max_failures and not ok:
        hook = storage.get_webhook(webhook_id)
        if hook is not None and hook["fail_count"] >= max_failures:
            storage.set_webhook_active(webhook_id, False)

    # Повторная попытка (с паузой RETRY_DELAY), если доставка не удалась.
    if not ok and attempts < MAX_ATTEMPTS:
        retry = dict(item)
        retry["attempts"] = attempts
        retry["not_before"] = time.time() + RETRY_DELAY
        key = (webhook_id, payload.get("event", ""),
               payload.get("data", {}).get("subject", ""))
        with _cond:
            _pending[key] = retry
            _cond.notify_all()


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
    with _cond:
        for h in matching:
            key = (h["id"], event, subject)
            _pending[key] = {
                "webhook_id": h["id"],
                "payload": payload,
                "attempts": 0,
                "delivery_id": uuid.uuid4().hex,
            }
        _cond.notify_all()
    _ensure_worker()
    return len(matching)


def replay_delivery(delivery_id: str,
                    tenant_id: Optional[int] = None) -> Dict:
    """Повторить записанную доставку (replay) — заново отправить её payload.

    ``delivery_id`` — id из истории доставок (заголовок ``X-MedRoster-Delivery``).
    ``tenant_id`` — ограничение доступа: API-ключ может повторять только
    доставки вебхуков своего тенанта (None — без ограничения, локальный админ).
    Повтор получает новый id доставки; исходная запись истории не меняется.
    """
    rec = storage.get_webhook_delivery(delivery_id, tenant_id=tenant_id)
    if rec is None:
        return {"ok": False, "error": "not_found"}
    hook = storage.get_webhook(rec["webhook_id"])
    if hook is None:
        return {"ok": False, "error": "webhook_deleted"}
    if not hook["is_active"]:
        return {"ok": False, "error": "webhook_inactive"}
    try:
        payload = json.loads(rec["payload"])
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad_payload"}
    new_id = uuid.uuid4().hex
    with _cond:
        _pending[(rec["webhook_id"], rec["event"], rec["subject"])] = {
            "webhook_id": rec["webhook_id"],
            "payload": payload,
            "attempts": 0,
            "delivery_id": new_id,
        }
        _cond.notify_all()
    _ensure_worker()
    return {"ok": True, "delivery_id": new_id, "event": rec["event"],
            "webhook_id": rec["webhook_id"]}


def pending_count() -> int:
    """Сколько доставок ждёт в очереди (для тестов и диагностики)."""
    with _cond:
        return len(_pending)


def wait_delivered(timeout: float = 5.0) -> bool:
    """Дождаться, пока очередь опустеет и воркер закончит текущую партию.

    True — все поставленные доставки обработаны (успешно или с ошибкой).
    В отличие от опроса «очередь пуста», нет окна между изъятием партии
    воркером и завершением доставки.
    """
    deadline = time.time() + timeout
    with _cond:
        while _pending or _busy:
            remaining = deadline - time.time()
            if remaining <= 0:
                return False
            _cond.wait(remaining)
    return True


def reset() -> None:
    """Очистить очередь (для тестов)."""
    with _cond:
        _pending.clear()
        _cond.notify_all()
