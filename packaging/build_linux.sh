#!/usr/bin/env bash
# ============================================================================
#  Сборка Linux-пакетов «МедГрафик: Поликлиника».
#
#  Результат (в packaging/output/):
#    med-roster-<VERSION>.tar.gz   — переносимая сборка (без venv)
#    med-roster_<VERSION>_amd64.deb — Debian / Ubuntu
#    med-roster-<VERSION>.x86_64.rpm — Fedora / Simply Linux и др.
#
#  Требования: python3, python3-venv, pip; для .deb/.rpm — fpm (ruby gem)
#    и rpm (rpmbuild). Установка: см. .github/workflows/release.yml.
# ============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
OUT="$ROOT/packaging/output"
STAGE="$ROOT/build/linux-stage"
APP_DIR="$STAGE/opt/med-roster"
USR_BIN="$STAGE/usr/bin"
USR_APPS="$STAGE/usr/share/applications"
USR_ICONS="$STAGE/usr/share/icons/hicolor/scalable/apps"

# --- версия из app/__init__.py ---
VERSION="$(python3 packaging/get_version.py)"
ARCH="amd64"

rm -rf "$OUT" "$STAGE"
mkdir -p "$OUT" "$APP_DIR" "$USR_BIN" "$USR_APPS" "$USR_ICONS"

echo "Сборка med-roster v${VERSION} (Linux, ${ARCH})"

# --- копируем исходники приложения (без мусора и персональных данных) ---
cp -r "$ROOT/app" "$APP_DIR/app"
cp "$ROOT/run.py" "$APP_DIR/run.py"
cp "$ROOT/requirements.txt" "$APP_DIR/requirements.txt"

# --- системные файлы: лаунчер, ярлык меню, иконка ---
cp "$ROOT/packaging/linux/med-roster" "$USR_BIN/med-roster"
chmod +x "$USR_BIN/med-roster"
cp "$ROOT/packaging/linux/med-roster.desktop" "$USR_APPS/med-roster.desktop"
cp "$ROOT/packaging/linux/med-roster.svg" "$USR_ICONS/med-roster.svg"

# --- переносимая сборка tar.gz ---
echo "[1/3] переносимый архив tar.gz"
mkdir -p "$STAGE/med-roster"
cp -r "$APP_DIR/." "$STAGE/med-roster/"
cp "$ROOT/start.sh" "$STAGE/med-roster/start.sh"
chmod +x "$STAGE/med-roster/start.sh"
tar -C "$STAGE" -czf "$OUT/med-roster-${VERSION}.tar.gz" med-roster

# --- .deb / .rpm через fpm ---
# Важно для fpm >= 1.16: все флаги ДО позиционных аргументов, а исходные пути —
# только относительные к -C (иначе fpm удваивает путь и падает с «Cannot chdir»).
if command -v fpm >/dev/null 2>&1; then
    echo "[2/3] сборка .deb"
    fpm -s dir -t deb \
        -n med-roster -v "$VERSION" -a "$ARCH" \
        --description "Расчёт графиков сменности и табелей рабочего времени" \
        --url "https://github.com/Chistovik92/med-roster" \
        --depends "python3" --depends "python3-venv" --depends "python3-pip" \
        --after-install "$ROOT/packaging/linux/after-install.sh" \
        -p "$OUT/med-roster_${VERSION}_${ARCH}.deb" \
        -C "$STAGE" \
        opt usr

    echo "[3/3] сборка .rpm"
    # На Fedora/Simply Linux нет пакета python3-venv (venv идёт вместе с pip).
    fpm -s dir -t rpm \
        -n med-roster -v "$VERSION" -a x86_64 \
        --description "Расчёт графиков сменности и табелей рабочего времени" \
        --url "https://github.com/Chistovik92/med-roster" \
        --depends "python3" --depends "python3-pip" \
        --after-install "$ROOT/packaging/linux/after-install.sh" \
        -p "$OUT/med-roster-${VERSION}.x86_64.rpm" \
        -C "$STAGE" \
        opt usr
else
    echo "[ПРОПУСК] fpm не найден — .deb/.rpm не собраны (см. CI release.yml)."
fi

echo
echo "Готово. Артефакты в $OUT:"
ls -1 "$OUT" 2>/dev/null || true
