# -*- coding: utf-8 -*-
"""Тесты остановки сервиса (/api/shutdown).

Проверяется, что:
  * ``/api/shutdown`` и ``/api/v1/shutdown`` доступны по POST (в новых
    версиях FastAPI include_router ленивый, поэтому регистрация проверяется
    реальным запросом, а не перебором ``app.routes``);
  * планировщик ``_schedule_shutdown`` вызывает остановку процесса
    (вместо ``_stop_process`` подставляется безвредная заглушка, поэтому
    тест можно запускать сколько угодно раз);
  * остановка сервиса запрещена для внешних клиентов без прав администратора.
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import app.main as main
from app.core import api_auth


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDROSTER_DATA_DIR", str(tmp_path))
    api_auth.reset_cache()
    main._sessions.clear()
    yield
    api_auth.reset_cache()
    main._sessions.clear()


def test_shutdown_route_registered():
    """POST /api/shutdown и /api/v1/shutdown отвечают (роуты подключены)."""
    from fastapi.testclient import TestClient

    called = threading.Event()

    def fake_stop():
        called.set()

    patches = pytest.MonkeyPatch()
    patches.setattr(main, "_stop_process", fake_stop)
    patches.setattr(main, "SHUTDOWN_DELAY", 0.05)
    try:
        client = TestClient(main.app, client=("127.0.0.1", 50000))
        for path in ("/api/shutdown", "/api/v1/shutdown"):
            resp = client.post(path)
            assert resp.status_code == 200, path
            assert resp.json()["status"] == "stopping"
        assert called.wait(timeout=2.0)
    finally:
        patches.undo()


def test_shutdown_forbidden_for_remote():
    """Внешний клиент не может остановить сервис (403, процесс жив)."""
    from fastapi.testclient import TestClient

    client = TestClient(main.app, client=("10.0.0.7", 50000))
    resp = client.post("/api/shutdown")
    assert resp.status_code == 403


def test_schedule_shutdown_calls_stop(monkeypatch):
    called = threading.Event()

    def fake_stop():
        called.set()

    monkeypatch.setattr(main, "_stop_process", fake_stop)
    monkeypatch.setattr(main, "SHUTDOWN_DELAY", 0.01)

    main._schedule_shutdown()
    assert called.wait(timeout=2.0)
