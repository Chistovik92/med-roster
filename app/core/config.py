# -*- coding: utf-8 -*-
"""Конфигурация интеграционного слоя (API-ключи, rate limit, CORS, аудит).

Все параметры читаются из переменных окружения и имеют безопасные значения
по умолчанию, чтобы поведение «из коробки» не изменилось:
локальный запуск (127.0.0.1) продолжает работать без ключей и ограничений.

Переменные (все необязательные):

* ``MEDROSTER_CORS_ORIGINS`` — источники через запятую для CORS
  (например ``https://mis.clinic.local,http://localhost:3000``).
  Пусто/не задано → ``*`` (все; безопасно, пока сервер слушает только 127.0.0.1).
* ``MEDROSTER_RATE_LIMIT`` — запросов в окно для обычных эндпоинтов (по умолчанию 70).
* ``MEDROSTER_HEAVY_RATE_LIMIT`` — запросов в окно для «тяжёлых» эндпоинтов
  (импорт .xls/.db, экспорт CSV/XLS/HTML; по умолчанию 10).
* ``MEDROSTER_RATE_LIMIT_WINDOW`` — размер окна в секундах (по умолчанию 60).
* ``MEDROSTER_REQUIRE_API_KEY`` — ``1`` требовать ключ даже при отсутствии
  настроенных ключей (по умолчанию ``0``: без ключей сервер работает в открытом
  режиме, как раньше).
* ``MEDROSTER_TRUST_PROXY`` — ``1`` доверять заголовку ``X-Forwarded-For``
  (когда сервер за reverse proxy; по умолчанию ``0``).
* ``MEDROSTER_ADMIN_TOKEN`` — секрет для удалённого доступа к управлению
  ключами и аудитом (заголовок ``X-Admin-Token``). Пусто → управление ключами
  доступно только с локального компьютера.
* ``MEDROSTER_AUDIT_ENABLED`` — ``0`` отключить аудит-лог (по умолчанию ``1``).
* ``MEDROSTER_AUDIT_RETENTION_DAYS`` — сколько дней хранить записи аудита
  (по умолчанию 90).

Важно для тестов: значения читаются в момент запроса (middleware обращается к
атрибутам модуля), поэтому их можно менять через monkeypatch без перезапуска.
CORS читается один раз при старте приложения.
"""
from __future__ import annotations

import os

_TRUE_VALUES = ("1", "true", "yes", "on")


def _bool_env(name: str, default: str = "0") -> bool:
    value = os.environ.get(name, default)
    return value.strip().lower() in _TRUE_VALUES


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


# --- CORS ------------------------------------------------------------------ #
# Список источников, разделённых запятой. Пусто → разрешить все («*»).
CORS_ORIGINS = [o.strip() for o in os.environ.get("MEDROSTER_CORS_ORIGINS", "").split(",")
                if o.strip()]

# --- Ограничение частоты запросов (rate limiting) --------------------------- #
RATE_LIMIT_PER_MIN = _int_env("MEDROSTER_RATE_LIMIT", 70)          # обычные
HEAVY_RATE_LIMIT_PER_MIN = _int_env("MEDROSTER_HEAVY_RATE_LIMIT", 10)  # тяжёлые
RATE_LIMIT_WINDOW = _int_env("MEDROSTER_RATE_LIMIT_WINDOW", 60)    # окно, сек

# --- Авторизация ------------------------------------------------------------ #
# Требовать API-ключ от всех запросов, даже если ни один ключ ещё не создан.
# Локальные запросы (UI с того же компьютера) ключа не требуют никогда.
REQUIRE_API_KEY = _bool_env("MEDROSTER_REQUIRE_API_KEY", "0")

# Доверять X-Forwarded-For (сервер за reverse proxy: nginx и т.п.).
TRUST_PROXY = _bool_env("MEDROSTER_TRUST_PROXY", "0")

# --- Администрирование ------------------------------------------------------- #
# Секрет для удалённого управления ключами/аудитом (X-Admin-Token).
ADMIN_TOKEN = os.environ.get("MEDROSTER_ADMIN_TOKEN", "").strip()

# --- Аудит ------------------------------------------------------------------- #
AUDIT_ENABLED = _bool_env("MEDROSTER_AUDIT_ENABLED", "1")
AUDIT_RETENTION_DAYS = _int_env("MEDROSTER_AUDIT_RETENTION_DAYS", 90)
