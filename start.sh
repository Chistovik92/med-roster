#!/usr/bin/env bash
# med-roster — МедГрафик: Поликлиника (Linux: Debian 11–13 / Ubuntu)
set -e
cd "$(dirname "$0")"

echo "=========================================="
echo "  med-roster — МедГрафик: Поликлиника"
echo "  Сервер: http://127.0.0.1:25625"
echo "=========================================="
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python3 не найден. Установите Python 3.8+."
    exit 1
fi

# Проверка: не запущен ли уже сервис на порту 25625.
if (echo > /dev/tcp/127.0.0.1/25625) 2>/dev/null; then
    echo
    echo "[ПРЕДУПРЕЖДЕНИЕ] Сервис уже запущен на порту 25625."
    echo "Остановите его (./stop.sh или кнопка «Выключить сервис») и повторите."
    exit 1
fi

python3 -m uvicorn app.main:app --host 127.0.0.1 --port 25625
