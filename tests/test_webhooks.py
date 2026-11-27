# -*- coding: utf-8 -*-
"""Тесты Фазы 2: вебхуки — CRUD, доставка, подпись, коалесцинг, тенанты.

Доставка подменяется фейковым ``urlopen`` (сеть не используется), поток
доставки — реальный фоновый (как в проде), ожидание — ``wait_delivered``.
"""
import hashlib
import hmac
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import app.main as main
from app.core import api_auth, config, storage
from app.services import webhooks
from fastapi.testclient import TestClient

LOCAL = ("127.0.0.1", 50000)
REMOTE = ("10.0.0.5", 50000)


class _FakeResponse:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDROSTER_DATA_DIR", str(tmp_path))
    api_auth.reset_cache()
    main._sessions.clear()
    webhooks.reset()
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 10000)
    monkeypatch.setattr(config, "HEAVY_RATE_LIMIT_PER_MIN", 10000)
    # доставка всегда «успешна», если тест не подменяет поведение
    monkeypatch.setattr(webhooks, "_urlopen",
                        lambda req, timeout=None: _FakeResponse(200))
    yield
    api_auth.reset_cache()
    main._sessions.clear()
    webhooks.reset()


def _local():
    return TestClient(main.app, client=LOCAL)


def _remote():
    return TestClient(main.app, client=REMOTE)


def _create_hook(client=None, **over):
    body = {"url": "https://mis.example.local/hook", "tenant": "МИС Тест"}
    body.update(over)
    resp = (client or _local()).post("/api/v1/webhooks", json=body)
    assert resp.status_code == 200
    return resp.json()


def _deliveries(monkeypatch):
    """Собиратель доставок: возвращает (список, фейковый urlopen)."""
    calls = []

    def fake(req, timeout=None):
        calls.append({
            "url": req.full_url,
            "body": req.data,
            "headers": {k.lower(): v for k, v in req.headers.items()},
        })
        return _FakeResponse(200)

    monkeypatch.setattr(webhooks, "_urlopen", fake)
    return calls


# --------------------------------------------------------------------------- #
#  CRUD вебхуков
# --------------------------------------------------------------------------- #
def test_webhook_create_and_list():
    info = _create_hook()
    assert info["secret"].startswith("mrwh_")
    assert info["is_active"] is True
    # по умолчанию подписка на все события, кроме webhook.test
    assert "month.saved" in info["events"]
    assert "webhook.test" not in info["events"]

    hooks = _local().get("/api/v1/webhooks").json()["webhooks"]
    assert len(hooks) == 1
    hook = hooks[0]
    assert hook["url"] == info["url"]
    assert hook["has_secret"] is True
    assert "secret" not in hook                 # секрет не утекает в списке


def test_webhook_create_validation():
    client = _local()
    # плохой url
    r = client.post("/api/v1/webhooks",
                    json={"url": "ftp://x", "tenant": "Т"})
    assert r.status_code == 422
    # неизвестное событие
    r = client.post("/api/v1/webhooks", json={
        "url": "https://x.local/h", "tenant": "Т",
        "events": ["month.saved", "нет такого"]})
    assert r.status_code == 422
    # локальный админ обязан указать тенант
    r = client.post("/api/v1/webhooks", json={"url": "https://x.local/h"})
    assert r.status_code == 422


def test_webhook_delete_and_activate():
    client = _local()
    info = _create_hook()
    wid = info["id"]

    r = client.post("/api/v1/webhooks/%d/activate" % wid, json={"active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    hooks = client.get("/api/v1/webhooks").json()["webhooks"]
    assert hooks[0]["is_active"] is False

    assert client.delete("/api/v1/webhooks/%d" % wid).status_code == 200
    assert client.get("/api/v1/webhooks").json()["webhooks"] == []
    assert client.delete("/api/v1/webhooks/%d" % wid).status_code == 404


# --------------------------------------------------------------------------- #
#  Доставка и подпись
# --------------------------------------------------------------------------- #
def test_delivery_with_signature(monkeypatch):
    calls = _deliveries(monkeypatch)
    info = _create_hook(events=["month.saved"])
    client = _local()

    client.post("/api/v1/roster", json={
        "year": 2026, "month": 11, "save": True,
        "employees": [{"name": "Иванова И.И."}]})

    assert webhooks.wait_delivered()
    assert len(calls) >= 1
    call = calls[-1]
    assert call["url"] == info["url"]

    payload = json.loads(call["body"].decode("utf-8"))
    assert payload["event"] == "month.saved"
    assert payload["data"]["year"] == 2026
    assert payload["data"]["month"] == 11

    # подпись HMAC-SHA256 тела с секретом вебхука
    sig_header = call["headers"]["x-medroster-signature"]
    assert sig_header.startswith("sha256=")
    expected = hmac.new(info["secret"].encode("utf-8"), call["body"],
                        hashlib.sha256).hexdigest()
    assert sig_header == "sha256=" + expected
    assert call["headers"]["x-medroster-event"] == "month.saved"
    assert call["headers"]["x-medroster-delivery"]


def test_schedule_changed_on_cell_edit(monkeypatch):
    calls = _deliveries(monkeypatch)
    _create_hook(events=["schedule.changed"])
    client = _local()

    sid = client.post("/api/v1/roster", json={
        "year": 2026, "month": 11,
        "employees": [{"name": "Иванова И.И."}]}).json()["session_id"]
    calls.clear()
    client.post("/api/v1/session/%s/cell" % sid,
                json={"row_index": 0, "day": 2, "value": "8-15,48"})

    assert webhooks.wait_delivered()
    events = [json.loads(c["body"].decode("utf-8")) for c in calls]
    assert any(e["event"] == "schedule.changed"
              and e["data"]["action"] == "cell"
              and e["data"]["session_id"] == sid for e in events)


def test_coalescing_rapid_events(monkeypatch):
    """Быстрые повторные события по одному объекту склеиваются."""
    calls = _deliveries(monkeypatch)
    _create_hook(events=["schedule.changed"])
    monkeypatch.setattr(webhooks, "_POLL_INTERVAL", 0.5)

    for i in range(5):
        webhooks.emit_event("schedule.changed",
                            {"subject": "s1", "seq": i})
    assert webhooks.wait_delivered(timeout=6.0)
    # 5 событий не могут дать 5 доставок: очередь склеила их в 1-2
    assert 1 <= len(calls) <= 2
    payload = json.loads(calls[-1]["body"].decode("utf-8"))
    assert payload["data"]["seq"] == 4          # доставлено самое свежее


def test_month_deleted_event(monkeypatch):
    calls = _deliveries(monkeypatch)
    _create_hook(events=["month.deleted"])
    client = _local()

    saved_id = client.post("/api/v1/roster", json={
        "year": 2026, "month": 11, "save": True,
        "employees": [{"name": "Иванова И.И."}]}).json()["saved_id"]
    calls.clear()
    client.delete("/api/v1/saved/%d" % saved_id)

    assert webhooks.wait_delivered()
    payload = json.loads(calls[-1]["body"].decode("utf-8"))
    assert payload["event"] == "month.deleted"
    assert payload["data"]["saved_id"] == saved_id


def test_no_delivery_without_subscription(monkeypatch):
    calls = _deliveries(monkeypatch)
    _create_hook(events=["month.deleted"])   # подписан только на удаление
    client = _local()
    client.post("/api/v1/roster", json={
        "year": 2026, "month": 11, "save": True,
        "employees": [{"name": "Иванова И.И."}]})
    assert webhooks.wait_delivered()
    assert calls == []                        # month.saved не доставляется


def test_webhook_test_endpoint(monkeypatch):
    calls = _deliveries(monkeypatch)
    info = _create_hook()   # webhook.test не входит в подписку по умолчанию
    r = _local().post("/api/v1/webhooks/%d/test" % info["id"])
    assert r.status_code == 200 and r.json()["queued"] == 1

    assert webhooks.wait_delivered()
    payload = json.loads(calls[-1]["body"].decode("utf-8"))
    assert payload["event"] == "webhook.test"


def test_auto_disable_after_failures(monkeypatch):
    def failing(req, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(webhooks, "_urlopen", failing)
    monkeypatch.setattr(config, "WEBHOOK_MAX_FAILURES", 3)
    info = _create_hook(events=["month.saved"])
    client = _local()

    for _ in range(3):
        client.post("/api/v1/roster", json={
            "year": 2026, "month": 11, "save": True,
            "employees": [{"name": "Иванова И.И."}]})
        assert webhooks.wait_delivered()

    hook = storage.get_webhook(info["id"])
    assert hook["is_active"] is False          # отключён после серии неудач
    assert hook["fail_count"] >= 3
    assert hook["last_status"] is None        # сеть не ответила


def test_retry_then_success(monkeypatch):
    """Неудачная доставка ретраится; успех сбрасывает счётчик неудач."""
    calls = _deliveries(monkeypatch)
    info = _create_hook(events=["month.saved"])
    state = {"fail_first": True}

    def flaky(req, timeout=None):
        if state["fail_first"]:
            state["fail_first"] = False
            raise OSError("timeout")
        calls.append({"url": req.full_url})
        return _FakeResponse(200)

    monkeypatch.setattr(webhooks, "_urlopen", flaky)
    webhooks.emit_event("month.saved", {"subject": "1", "saved_id": 1})
    assert webhooks.wait_delivered()

    hook = storage.get_webhook(info["id"])
    assert hook["fail_count"] == 0            # успех сбросил счётчик
    assert hook["last_status"] == 200
    assert len(calls) == 1                   # ретрай дошёл


# --------------------------------------------------------------------------- #
#  Разграничение по тенантам
# --------------------------------------------------------------------------- #
def test_webhook_tenant_scoping():
    key_a = api_auth.create_key("МИС Альфа")
    key_b = api_auth.create_key("МИС Бета")
    remote = _remote()
    ha = {"X-API-Key": key_a["key"]}
    hb = {"X-API-Key": key_b["key"]}

    # ключ создаёт вебхук для своего тенанта (tenant в теле игнорируется)
    r = remote.post("/api/v1/webhooks", json={
        "url": "https://alpha.local/hook", "tenant": "МИС Чужая"},
        headers=ha)
    assert r.status_code == 200
    wid = r.json()["id"]

    # свой ключ видит, чужой — нет
    assert len(remote.get("/api/v1/webhooks", headers=ha).json()["webhooks"]) == 1
    assert remote.get("/api/v1/webhooks", headers=hb).json()["webhooks"] == []

    # чужой ключ не может удалить/отключить
    assert remote.delete("/api/v1/webhooks/%d" % wid, headers=hb).status_code == 404
    r = remote.post("/api/v1/webhooks/%d/activate" % wid,
                    json={"active": False}, headers=hb)
    assert r.status_code == 404
    r = remote.post("/api/v1/webhooks/%d/test" % wid, headers=hb)
    assert r.status_code == 404

    # свой ключ может
    assert remote.delete("/api/v1/webhooks/%d" % wid, headers=ha).status_code == 200
    # локальный админ видит все (после удаления — пусто)
    assert _local().get("/api/v1/webhooks").json()["webhooks"] == []
