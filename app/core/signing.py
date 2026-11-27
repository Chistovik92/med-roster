# -*- coding: utf-8 -*-
"""Подпись пакетов экспорта (HMAC-SHA256).

Назначение: гарантировать получателю (МИС, кадрам, архиву), что файлы
экспорта не изменялись после выгрузки из «МедГрафика». Для каждого файла
считаются:

* ``sha256``       — контрольная сумма содержимого (детект изменений);
* ``hmac_sha256``  — подпись с серверным секретом (защита от подделки:
  сумму нельзя пересчитать, не зная секрета).

Секрет берётся из ``MEDROSTER_SIGN_SECRET``; если переменная не задана —
генерируется один раз и сохраняется в БД (таблица ``settings``), поэтому
подписи стабильны между перезапусками программы.

Важно: это подпись целостности, а не юридически значимая ЭЦП (для
последней требуется сертификат удостоверяющего центра и ГОСТ-криптография,
которые нельзя переносимо реализовать на Python 3.8 stdlib). Проверить
подпись можно из любого языка, например на Python:

    hmac.new(secret.encode(), data, hashlib.sha256).hexdigest() == sig
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import secrets as _secrets
import threading
from typing import Dict, Optional

from app.core import config, storage

_SETTING_KEY = "sign_secret"

# Автогенерация секрета: под lock, чтобы два параллельных запроса не создали
# разные секреты (один из них «потерялся» бы в БД, и его подписи перестали
# бы проходить проверку).
_secret_lock = threading.Lock()


def get_sign_secret() -> str:
    """Секрет подписи: env ``MEDROSTER_SIGN_SECRET`` или автогенерация в БД."""
    if config.SIGN_SECRET:
        return config.SIGN_SECRET
    with _secret_lock:
        stored = storage.get_setting(_SETTING_KEY)
        if stored:
            return stored
        generated = _secrets.token_hex(32)
        storage.set_setting(_SETTING_KEY, generated)
        return generated


def sign_bytes(data: bytes, secret: Optional[str] = None) -> Dict[str, str]:
    """Подписать содержимое: SHA-256 суммы + HMAC-SHA256 (hex)."""
    if isinstance(data, str):  # допуск: текст кодируем в UTF-8
        data = data.encode("utf-8")
    if secret is None:
        secret = get_sign_secret()
    digest = hashlib.sha256(data).hexdigest()
    signature = _hmac.new(secret.encode("utf-8"), data, hashlib.sha256).hexdigest()
    return {"sha256": digest, "hmac_sha256": signature}


def verify_bytes(data: bytes, signature: str,
                 secret: Optional[str] = None) -> bool:
    """Проверить HMAC-подпись содержимого (сравнение за постоянное время)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    if not signature:
        return False
    if secret is None:
        secret = get_sign_secret()
    expected = _hmac.new(secret.encode("utf-8"), data, hashlib.sha256).hexdigest()
    return _hmac.compare_digest(expected, signature.strip().lower())
