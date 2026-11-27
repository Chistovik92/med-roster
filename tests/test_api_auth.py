# -*- coding: utf-8 -*-
"""Тесты интеграционного слоя: API-ключи, тенанты, авторизация, /api/v1.

Сценарии:
  * генерация/создание ключа → авторизация по X-API-Key из «внешней» сети;
  * неверный и отозванный ключ → 401;
  * внешний клиент без ключа: 401, когда ключи настроены; доступ (открытый
    режим), когда ключей нет — обратная совместимость;
  * локальный клиент (UI) работает без ключа всегда;
  * управление ключами доступно только локально / по X-Admin-Token;
  * роуты /api и /api/v1 указывают на одни и те же обработчики;
  * OpenAPI-схема описывает только /api/v1.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import app.main as main
from app.core import api_auth, config
from fastapi.testclient import TestClient

LOCAL = ("127.0.0.1", 50000)
REMOTE = ("10.0.0.5", 50000)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDROSTER_DATA_DIR", str(tmp_path))
    api_auth.reset_cache()
    main._sessions.clear()
    # на время тестов выключаем rate limit, чтобы не мешал
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 10000)
    monkeypatch.setattr(config, "HEAVY_RATE_LIMIT_PER_MIN", 10000)
    yield
    api_auth.reset_cache()
    main._sessions.clear()


def _local_client():
    return TestClient(main.app, client=LOCAL)


def _remote_client():
    return TestClient(main.app, client=REMOTE)


# --------------------------------------------------------------------------- #
#  Модуль api_auth
# --------------------------------------------------------------------------- #
def test_generate_key_format():
    key = api_auth.generate_key()
    assert key.startswith("mrk_")
    assert len(key) == len("mrk_") + 40
    int(key[len("mrk_"):], 16)  # hex
    # ключи не повторяются
    assert api_auth.generate_key() != api_auth.generate_key()


def test_create_and_verify_key():
    info = api_auth.create_key("МИС Поликлиника", label="интеграция")
    assert info["key"].startswith("mrk_")
    assert info["tenant"] == "МИС Поликлиника"
    assert info["prefix"] == info["key"][:12]

    verified = api_auth.verify_key(info["key"])
    assert verified is not None
    assert verified["id"] == info["id"]
    assert verified["tenant"] == "МИС Поликлиника"
    assert verified["label"] == "интеграция"

    # неверный ключ
    assert api_auth.verify_key("mrk_" + "0" * 40) is None
    assert api_auth.verify_key("") is None
    assert api_auth.verify_key("not-a-key") is None


def test_revoke_and_activate_key():
    info = api_auth.create_key("МИС А")
    assert api_auth.has_active_keys() is True

    assert api_auth.revoke_key(info["id"]) is True
    assert api_auth.verify_key(info["key"]) is None      # отозван
    assert api_auth.has_active_keys() is False           # кэш сброшен сразу

    assert api_auth.activate_key(info["id"]) is True
    assert api_auth.verify_key(info["key"]) is not None

    # несуществующий id
    assert api_auth.revoke_key(99999) is False


def test_list_keys_hides_secret():
    info = api_auth.create_key("МИС Б", label="тест")
    keys = api_auth.list_keys()
    assert len(keys) == 1
    k = keys[0]
    assert k["prefix"] == info["prefix"]
    assert "key" not in k and info["key"] not in str(k)   # секрет не утекает
    assert k["is_active"] is True
    assert k["tenant"] == "МИС Б"
    assert k["request_count"] == 0


def test_tenant_reused():
    api_auth.create_key("Поликлиника №16")
    api_auth.create_key("Поликлиника №16", label="второй ключ")
    tenants = api_auth.list_tenants()
    assert len(tenants) == 1
    assert tenants[0]["name"] == "Поликлиника №16"
    assert tenants[0]["active_keys"] == 2


# --------------------------------------------------------------------------- #
#  HTTP: авторизация через middleware
# --------------------------------------------------------------------------- #
def test_local_ui_works_without_key():
    client = _local_client()
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["app"] == "med-roster"


def test_v1_prefix_same_handlers():
    client = _local_client()
    legacy = client.get("/api/health").json()
    v1 = client.get("/api/v1/health").json()
    assert legacy == v1
    assert client.get("/api/v1/calendar/2026").status_code == 200


def test_remote_open_mode_without_keys():
    """Ключей нет и REQUIRE_API_KEY выключен → прежний открытый режим."""
    client = _remote_client()
    assert client.get("/api/health").status_code == 200


def test_remote_requires_key_when_keys_exist():
    client = _remote_client()
    # на изолированной БД ключей нет — создадим локально
    _local_client().post("/api/keys", json={"tenant": "МИС В"})

    resp = client.get("/api/health")
    assert resp.status_code == 401
    assert "API-ключ" in resp.json()["error"]


def test_remote_with_valid_key():
    info = api_auth.create_key("МИС Г", label="внешняя")
    client = _remote_client()
    resp = client.get("/api/v1/health", headers={"X-API-Key": info["key"]})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_remote_with_bad_key():
    api_auth.create_key("МИС Д")
    client = _remote_client()
    resp = client.get("/api/health", headers={"X-API-Key": "mrk_" + "ab" * 20})
    assert resp.status_code == 401


def test_revoked_key_rejected():
    info = api_auth.create_key("МИС Е")
    api_auth.revoke_key(info["id"])
    client = _remote_client()
    resp = client.get("/api/health", headers={"X-API-Key": info["key"]})
    assert resp.status_code == 401


def test_require_api_key_flag(monkeypatch):
    """REQUIRE_API_KEY=1 закрывает внешние запросы даже без настроенных ключей."""
    monkeypatch.setattr(config, "REQUIRE_API_KEY", True)
    client = _remote_client()
    assert client.get("/api/health").status_code == 401
    # локальный UI продолжает работать
    assert _local_client().get("/api/health").status_code == 200


# --------------------------------------------------------------------------- #
#  HTTP: управление ключами (только локально / X-Admin-Token)
# --------------------------------------------------------------------------- #
def test_key_management_local_only():
    remote = _remote_client()
    assert remote.get("/api/keys").status_code == 403
    assert remote.post("/api/keys", json={"tenant": "X"}).status_code == 403

    local = _local_client()
    resp = local.post("/api/keys", json={"tenant": "МИС Ж", "label": "основной"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["key"].startswith("mrk_")

    resp = local.get("/api/keys")
    assert resp.status_code == 200
    keys = resp.json()["keys"]
    assert len(keys) == 1
    assert keys[0]["tenant"] == "МИС Ж"
    assert "key" not in keys[0]

    # и через /api/v1
    assert local.get("/api/v1/keys").status_code == 200
    # внешний клиент с валидным ключом всё равно не управляет ключами
    ext_with_key = TestClient(main.app, client=REMOTE,
                              headers={"X-API-Key": data["key"]})
    assert ext_with_key.get("/api/keys").status_code == 403


def test_key_management_with_admin_token(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "s3cret-token")
    api_auth.create_key("МИС З")
    remote = _remote_client()
    # без токена — 403
    assert remote.get("/api/keys").status_code in (401, 403)
    # с токеном — можно
    ok = TestClient(main.app, client=REMOTE,
                    headers={"X-Admin-Token": "s3cret-token"})
    assert ok.get("/api/keys").status_code == 200
    resp = ok.post("/api/keys", json={"tenant": "МИС И"})
    assert resp.status_code == 200
    # отзыв и восстановление
    kid = resp.json()["id"]
    assert ok.delete("/api/keys/%d" % kid).status_code == 200
    assert ok.post("/api/keys/%d/activate" % kid).status_code == 200


def test_create_key_validation():
    local = _local_client()
    resp = local.post("/api/keys", json={"tenant": "   "})
    assert resp.status_code == 422


def test_shutdown_local_only_covered_by_own_module():
    """См. test_shutdown.py — здесь только уверенность, что путь под guard."""
    remote = _remote_client()
    assert remote.post("/api/v1/shutdown").status_code == 403


# --------------------------------------------------------------------------- #
#  OpenAPI-контракт
# --------------------------------------------------------------------------- #
def test_openapi_schema_v1_only():
    client = _local_client()
    resp = client.get("/api/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert paths, "схема не пустая"
    assert all(p.startswith("/api/v1") for p in paths), \
        "легаси-пути не должны попадать в контракт: %s" % \
        [p for p in paths if not p.startswith("/api/v1")]
    assert "/api/v1/keys" in paths
    assert "/api/v1/audit" in paths
    assert client.get("/api/docs").status_code == 200


def test_health_reports_version():
    from app import __version__
    client = _local_client()
    assert client.get("/api/health").json()["version"] == __version__
