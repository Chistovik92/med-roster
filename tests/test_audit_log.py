# -*- coding: utf-8 -*-
"""Тесты аудита HTTP-запросов.

Сценарии:
  * логируются ВСЕ запросы к /api/* (включая отклонённые 401/403/429);
  * для авторизованных запросов фиксируются ключ и тенант («чьим» ключом
    выполнялся запрос);
  * для отклонённых — причина (rejected_bad_key / rejected_no_key /
    forbidden_remote / rate_limited);
  * запросы к статике и корню не логируются;
  * статистика ключей (request_count / last_used_at) обновляется;
  * чтение /api/audit, сводка /api/audit/stats, очистка DELETE /api/audit;
  * аудит можно отключить (MEDROSTER_AUDIT_ENABLED=0).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import app.main as main
from app.core import api_auth, config
from fastapi.testclient import TestClient

LOCAL = ("127.0.0.1", 50000)
REMOTE = ("10.0.0.11", 50000)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDROSTER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 10000)
    api_auth.reset_cache()
    main._sessions.clear()
    yield
    api_auth.reset_cache()
    main._sessions.clear()


def _entries(limit=50, **filters):
    return main.audit_log.recent(limit=limit, **filters)


def test_audit_logs_local_requests():
    client = TestClient(main.app, client=LOCAL)
    client.get("/api/health")
    main.audit_log.flush()
    entries = _entries()
    assert entries
    e = entries[0]
    assert e["method"] == "GET"
    assert e["path"] == "/api/health"
    assert e["status"] == 200
    assert e["auth_status"] == "anonymous_local"
    assert e["client_ip"] == "127.0.0.1"
    assert e["duration_ms"] is not None


def test_audit_authorized_request_records_tenant():
    info = api_auth.create_key("МИС Учёт", label="ключ №1")
    client = TestClient(main.app, client=REMOTE)
    client.get("/api/health", headers={"X-API-Key": info["key"]})
    main.audit_log.flush()
    entries = _entries(auth_status="authorized")
    assert entries
    e = entries[0]
    assert e["api_key_id"] == info["id"]
    assert e["tenant"] == "МИС Учёт"
    assert e["status"] == 200


def test_audit_rejected_bad_key():
    api_auth.create_key("МИС Эталон")
    client = TestClient(main.app, client=REMOTE)
    resp = client.get("/api/health", headers={"X-API-Key": "mrk_" + "cd" * 20})
    assert resp.status_code == 401
    main.audit_log.flush()
    entries = _entries(auth_status="rejected_bad_key")
    assert entries
    assert entries[0]["status"] == 401
    assert entries[0]["api_key_id"] is None


def test_audit_rejected_no_key():
    api_auth.create_key("МИС Замок")
    client = TestClient(main.app, client=REMOTE)
    resp = client.get("/api/health")
    assert resp.status_code == 401
    main.audit_log.flush()
    entries = _entries(auth_status="rejected_no_key")
    assert entries
    assert entries[0]["status"] == 401
    assert entries[0]["api_key_id"] is None


def test_audit_forbidden_remote_admin_endpoint():
    client = TestClient(main.app, client=REMOTE)
    resp = client.get("/api/keys")
    assert resp.status_code in (401, 403)
    main.audit_log.flush()
    entries = _entries(auth_status="forbidden_remote")
    assert entries
    assert entries[0]["path"] == "/api/keys"


def test_audit_key_usage_stats_updated():
    info = api_auth.create_key("МИС Статистика")
    client = TestClient(main.app, client=REMOTE)
    for _ in range(3):
        client.get("/api/health", headers={"X-API-Key": info["key"]})
    main.audit_log.flush()
    keys = api_auth.list_keys()
    k = [x for x in keys if x["id"] == info["id"]][0]
    assert k["request_count"] == 3
    assert k["last_used_at"] is not None
    assert k["last_used_at"] >= k["created_at"]


def test_audit_skips_non_api_paths():
    client = TestClient(main.app, client=LOCAL)
    client.get("/")
    client.get("/static/app.js")
    main.audit_log.flush()
    for e in _entries():
        assert e["path"].startswith("/api")


def test_audit_http_read_and_clear():
    client = TestClient(main.app, client=LOCAL)
    client.get("/api/health")
    main.audit_log.flush()

    resp = client.get("/api/audit?limit=5")
    assert resp.status_code == 200
    assert resp.json()["entries"]

    resp = client.get("/api/audit/stats")
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["total"] >= 1
    assert "anonymous_local" in stats["by_status"]

    # очистка только старых записей (0 дней → всё старое)
    resp = client.delete("/api/audit?older_than_days=0")
    assert resp.status_code == 200
    assert resp.json()["removed"] >= 1
    # сам запрос очистки логируется (аудит пишется ПОСЛЕ обработки)
    # это правильное поведение: в журнале остаются только записи после очистки.
    remaining = _entries()
    assert all(e["path"] == "/api/audit" for e in remaining)

    # фильтрация по ключу
    info = api_auth.create_key("МИС Фильтр")
    ext = TestClient(main.app, client=REMOTE)
    ext.get("/api/health", headers={"X-API-Key": info["key"]})
    client.get("/api/health")
    main.audit_log.flush()
    resp = client.get("/api/audit?key_id=%d" % info["id"])
    entries = resp.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["tenant"] == "МИС Фильтр"


def test_audit_admin_endpoints_local_only():
    remote = TestClient(main.app, client=REMOTE)
    assert remote.get("/api/audit").status_code in (401, 403)


def test_audit_can_be_disabled(monkeypatch):
    monkeypatch.setattr(config, "AUDIT_ENABLED", False)
    client = TestClient(main.app, client=LOCAL)
    client.get("/api/health")
    main.audit_log.flush()
    assert _entries() == []


def test_audit_retention_prunes_old_entries():
    info = api_auth.create_key("МИС Ретенция")
    client = TestClient(main.app, client=REMOTE)
    client.get("/api/health", headers={"X-API-Key": info["key"]})
    main.audit_log.flush()
    # «состарить» записи и подчистить
    from app.core import storage
    conn = storage.get_connection()
    try:
        conn.execute("UPDATE api_audit_log SET ts = ts - 400 * 86400")
        conn.commit()
    finally:
        conn.close()
    removed = main.audit_log.clear(older_than_days=365)
    assert removed >= 1
    assert _entries() == []
