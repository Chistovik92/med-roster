# -*- coding: utf-8 -*-
"""Тесты ограничения частоты запросов (rate limiting).

Сценарии:
  * обычные эндпоинты: лимит RATE_LIMIT_PER_MIN за окно;
  * «тяжёлые» (экспорт/импорт): отдельный, более строгий лимит;
  * превышение → 429 + Retry-After;
  * локальный UI лимитами не ограничивается;
  * лимиты независимы по субъектам (разные ключи — разные счётчики);
  * счётчик сбрасывается по истечении окна.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import app.main as main
from app.core import api_auth, config
from app.core.rate_limiter import RateLimiter
from fastapi.testclient import TestClient

LOCAL = ("127.0.0.1", 50000)
REMOTE = ("10.0.0.9", 50000)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDROSTER_DATA_DIR", str(tmp_path))
    api_auth.reset_cache()
    main._sessions.clear()
    main.rate_limiter.reset()
    yield
    api_auth.reset_cache()
    main._sessions.clear()
    main.rate_limiter.reset()


def _key():
    info = api_auth.create_key("МИС Лимит")
    return info["key"]


def _remote():
    return TestClient(main.app, client=REMOTE)


def _make_session(client, headers=None):
    resp = client.post("/api/schedule", json={"year": 2026, "month": 11},
                       headers=headers)
    assert resp.status_code == 200
    return resp.json()["session_id"]


# --------------------------------------------------------------------------- #
#  Модуль RateLimiter (юнит-уровень)
# --------------------------------------------------------------------------- #
def test_limiter_allows_within_limit():
    limiter = RateLimiter()
    assert all(limiter.check("s", 5, 60.0) for _ in range(5))


def test_limiter_blocks_above_limit():
    limiter = RateLimiter()
    for _ in range(3):
        assert limiter.check("s", 3, 60.0)
    assert limiter.check("s", 3, 60.0) is False
    assert limiter.check("s", 3, 60.0) is False


def test_limiter_window_reset():
    limiter = RateLimiter()
    limiter.check("s", 1, 0.05)
    assert limiter.check("s", 1, 0.05) is False
    time.sleep(0.06)
    assert limiter.check("s", 1, 0.05) is True


def test_limiter_subjects_independent():
    limiter = RateLimiter()
    assert limiter.check("a", 1, 60.0)
    assert limiter.check("b", 1, 60.0)
    assert limiter.check("a", 1, 60.0) is False
    assert limiter.check("b", 1, 60.0) is False


def test_limiter_retry_after():
    limiter = RateLimiter()
    limiter.check("s", 1, 60.0)
    remaining = limiter.retry_after("s", 60.0)
    assert 0.0 < remaining <= 60.0
    assert limiter.retry_after("unknown", 60.0) == 0.0


def test_limiter_cleanup():
    limiter = RateLimiter()
    limiter.check("old", 10, 0.05)
    time.sleep(0.06)
    limiter.cleanup(max_age=0.05)
    # после cleanup окно начнётся заново
    assert limiter.check("old", 1, 60.0) is True


# --------------------------------------------------------------------------- #
#  HTTP: лимиты через middleware (значения читаются в момент запроса)
# --------------------------------------------------------------------------- #
def test_http_limit_for_authorized_key(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 3)
    monkeypatch.setattr(config, "RATE_LIMIT_WINDOW", 60)
    key = _key()
    client = _remote()
    headers = {"X-API-Key": key}
    statuses = [client.get("/api/health", headers=headers).status_code
                for _ in range(5)]
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429
    assert statuses[4] == 429
    resp = client.get("/api/health", headers=headers)
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) >= 1


def test_http_local_ui_not_limited(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 2)
    client = TestClient(main.app, client=LOCAL)
    statuses = [client.get("/api/health").status_code for _ in range(10)]
    assert all(s == 200 for s in statuses)


def test_http_heavy_limit_stricter(monkeypatch):
    """Экспорт: HEAVY_RATE_LIMIT_PER_MIN, а не общий RATE_LIMIT_PER_MIN."""
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 50)
    monkeypatch.setattr(config, "HEAVY_RATE_LIMIT_PER_MIN", 2)
    monkeypatch.setattr(config, "RATE_LIMIT_WINDOW", 60)
    key = _key()
    client = _remote()
    headers = {"X-API-Key": key}
    sid = _make_session(client, headers)

    statuses = [client.get("/api/export/csv/%s" % sid, headers=headers).status_code
                for _ in range(4)]
    assert statuses[:2] == [200, 200]
    assert statuses[2] == 429
    # при этом лёгкий запрос тем же ключом всё ещё в пределах общего лимита
    assert client.get("/api/health", headers=headers).status_code == 200


def test_http_subjects_independent(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 2)
    monkeypatch.setattr(config, "RATE_LIMIT_WINDOW", 60)
    key1 = api_auth.create_key("МИС Первая")["key"]
    key2 = api_auth.create_key("МИС Вторая")["key"]
    client = _remote()
    for _ in range(2):
        assert client.get("/api/health", headers={"X-API-Key": key1}).status_code == 200
    assert client.get("/api/health", headers={"X-API-Key": key1}).status_code == 429
    # другой ключ — свой счётчик
    assert client.get("/api/health", headers={"X-API-Key": key2}).status_code == 200


def test_rate_limited_logged_with_key(monkeypatch):
    """429 попадает в аудит с указанием, чей именно ключ превысил лимит."""
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 1)
    monkeypatch.setattr(config, "RATE_LIMIT_WINDOW", 60)
    info = api_auth.create_key("МИС Перебор", label="агрессия")
    client = _remote()
    headers = {"X-API-Key": info["key"]}
    client.get("/api/health", headers=headers)
    resp = client.get("/api/health", headers=headers)
    assert resp.status_code == 429

    main.audit_log.flush()
    entries = main.audit_log.recent(limit=10, auth_status="rate_limited")
    assert entries, "должна появиться запись rate_limited"
    e = entries[0]
    assert e["api_key_id"] == info["id"]
    assert e["tenant"] == "МИС Перебор"
    assert e["status"] == 429
