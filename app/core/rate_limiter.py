# -*- coding: utf-8 -*-
"""Ограничение частоты запросов (rate limiting) по субъекту.

Субъект — API-ключ (для запросов с ключом) или IP-адрес (для запросов без
ключа от внешних клиентов). Локальные запросы UI ограничениями не считаются.

Алгоритм — фиксированное окно со счётчиком: просто, предсказуемо и без
внешних зависимостей (важно для Python 3.8 / Windows 7 и offline-установки).
На границе окна возможен короткий «двойной всплеск» — для защиты МИС-интеграции
это приемлемо.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Tuple


class RateLimiter:
    """Потокобезопасный счётчик запросов по субъектам (окно фиксированной длины).

    Внутреннее состояние: ``subject -> [window_start, count]``.
    Память ограничивается методом :meth:`cleanup` (вызывается владельцем
    периодически, например потоком аудита).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, Tuple[float, int]] = {}

    def check(self, subject: str, limit: int, window: float) -> bool:
        """Зарегистрировать запрос и вернуть True, если он в пределах лимита.

        ``limit`` — максимальное число запросов за ``window`` секунд.
        False означает «лимит превышен, запрос отклонить».
        """
        now = time.time()
        with self._lock:
            entry = self._counters.get(subject)
            if entry is None or now - entry[0] >= window:
                self._counters[subject] = (now, 1)
                return 1 <= limit
            count = entry[1] + 1
            self._counters[subject] = (entry[0], count)
            return count <= limit

    def retry_after(self, subject: str, window: float) -> float:
        """Сколько секунд осталось до сброса окна (для заголовка Retry-After)."""
        now = time.time()
        with self._lock:
            entry = self._counters.get(subject)
            if entry is None:
                return 0.0
            remaining = entry[0] + window - now
            return max(0.0, remaining)

    def cleanup(self, max_age: float) -> None:
        """Удалить счётчики неактивных субъектов (защита от роста памяти)."""
        now = time.time()
        with self._lock:
            stale = [k for k, v in self._counters.items() if now - v[0] > max_age]
            for k in stale:
                self._counters.pop(k, None)

    def reset(self) -> None:
        """Полностью сбросить состояние (используется в тестах)."""
        with self._lock:
            self._counters.clear()
