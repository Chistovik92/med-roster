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

python3 -m uvicorn app.main:app --host 127.0.0.1 --port 25625
