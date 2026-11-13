#!/bin/sh
# post-install для .deb / %post для .rpm (через fpm --after-install).
# Создаёт виртуальное окружение и ставит зависимости, чтобы /usr/bin/med-roster
# мог запускаться без ручных шагов. При отсутствии сети просто пропускается —
# тогда можно установить зависимости вручную (см. документацию).
set -e

APP_DIR="/opt/med-roster"

if command -v python3 >/dev/null 2>&1; then
    if [ ! -x "$APP_DIR/venv/bin/python3" ]; then
        python3 -m venv "$APP_DIR/venv" >/dev/null 2>&1 || true
    fi
    if [ -x "$APP_DIR/venv/bin/pip" ] && [ -f "$APP_DIR/requirements.txt" ]; then
        "$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt" >/dev/null 2>&1 || true
    fi
fi

exit 0
