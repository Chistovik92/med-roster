#!/usr/bin/env bash
# ============================================================
#  Остановка сервиса «МедГрафик: Поликлиника» (Linux).
#  Находит процесс, слушающий порт 25625, и завершает его.
#  Запуск:  ./stop.sh   (или  bash stop.sh)
# ============================================================
PORT=25625

echo "=========================================="
echo "  Остановка «МедГрафик: Поликлиника»"
echo "=========================================="
echo

# fuser — предпочтительный способ (пакет psmisc, есть на Debian/Ubuntu).
if command -v fuser >/dev/null 2>&1; then
    if fuser "${PORT}/tcp" >/dev/null 2>&1; then
        echo "Завершаю процесс(ы) на порту ${PORT} ..."
        fuser -k "${PORT}/tcp"
        echo
        echo "Готово. Сервис остановлен."
    else
        echo "Сервис не запущен (порт ${PORT} свободен)."
    fi
    exit 0
fi

# Запасной способ — lsof.
if command -v lsof >/dev/null 2>&1; then
    PIDS="$(lsof -ti "tcp:${PORT}" 2>/dev/null || true)"
    if [ -n "$PIDS" ]; then
        echo "Завершаю процессы: $PIDS"
        kill $PIDS 2>/dev/null || true
        echo
        echo "Готово. Сервис остановлен."
    else
        echo "Сервис не запущен (порт ${PORT} свободен)."
    fi
    exit 0
fi

echo "Не найдена утилита для остановки (fuser или lsof)."
echo "Остановите сервис вручную, например:"
echo "  kill \$(ss -tlnp | grep ':${PORT}' | awk '{print \$NF}' | grep -o '[0-9]*')"
exit 1
