# -*- coding: utf-8 -*-
"""Тесты остановки сервиса (/api/shutdown).

Проверяем, что:
  * маршрут ``/api/shutdown`` зарегистрирован и принимает POST;
  * планировщик ``_schedule_shutdown`` действительно завершает процесс
    (здесь ``_stop_process`` подменён заглушкой, чтобы не убивать тест).
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.main as main


def test_shutdown_route_registered():
    routes = {}
    for r in main.app.routes:
        if getattr(r, "path", "") == "/api/shutdown":
            routes["/api/shutdown"] = getattr(r, "methods", set())
    assert "/api/shutdown" in routes
    assert "POST" in routes.get("/api/shutdown", set())


def test_schedule_shutdown_calls_stop(monkeypatch):
    called = threading.Event()

    def fake_stop():
        called.set()

    monkeypatch.setattr(main, "_stop_process", fake_stop)
    monkeypatch.setattr(main, "SHUTDOWN_DELAY", 0.01)

    main._schedule_shutdown()
    assert called.wait(timeout=2.0)
