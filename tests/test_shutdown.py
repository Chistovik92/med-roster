# -*- coding: utf-8 -*-
"""Тесты остановки сервиса (/api/shutdown).

Проверяем, что:
  * маршрут ``/api/shutdown`` зарегистрирован и принимает POST;
  * планировщик ``_schedule_shutdown`` действительно завершает процесс
    (здесь ``_stop_process`` подменён заглушкой, чтобы не убивать тест).
"""
import sys, os, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.main as main

fails = 0
def check(name, cond):
    global fails
    if not cond:
        fails += 1
    print(("OK  " if cond else "FAIL") + " %s" % name)


# 1) маршрут /api/shutdown зарегистрирован и принимает POST
routes = {}
for r in main.app.routes:
    if getattr(r, "path", "") == "/api/shutdown":
        routes["/api/shutdown"] = getattr(r, "methods", set())
check("/api/shutdown зарегистрирован", "/api/shutdown" in routes)
check("/api/shutdown — метод POST", "POST" in routes.get("/api/shutdown", set()))

# 2) _schedule_shutdown вызывает _stop_process (через короткую паузу)
called = threading.Event()

def fake_stop():
    called.set()

main._stop_process = fake_stop
main.SHUTDOWN_DELAY = 0.01

main._schedule_shutdown()
check("_schedule_shutdown вызывает _stop_process", called.wait(timeout=2.0))

print("\nИТОГО ПРОВАЛОВ: %d" % fails)
sys.exit(1 if fails else 0)
