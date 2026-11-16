#!/usr/bin/env bash
# Установка/обновление «МедГрафик: Поликлиника» прямо из GitHub.
# curl -fsSL https://raw.githubusercontent.com/Chistovik92/med-roster/master/install.sh | bash
set -euo pipefail

REPO="Chistovik92/med-roster"
REF="${MEDROSTER_REF:-master}"
INSTALL_ROOT="${MEDROSTER_INSTALL_DIR:-$HOME/.local/share/med-roster}"
APP_DIR="$INSTALL_ROOT/app"
VENV="$INSTALL_ROOT/venv"
BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/med-roster"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

say() { printf '%s\n' "$*"; }
fail() { printf 'Ошибка установки: %s\n' "$*" >&2; exit 1; }

run_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        fail "нужны права root для установки Python (sudo не найден)"
    fi
}

install_python() {
    say "Установка Python и необходимых системных пакетов…"
    if command -v apt-get >/dev/null 2>&1; then
        run_root apt-get update
        run_root apt-get install -y python3 python3-venv python3-pip ca-certificates curl
    elif command -v dnf >/dev/null 2>&1; then
        run_root dnf install -y python3 python3-pip ca-certificates curl
    elif command -v yum >/dev/null 2>&1; then
        run_root yum install -y python3 python3-pip ca-certificates curl
    elif command -v zypper >/dev/null 2>&1; then
        run_root zypper --non-interactive install python3 python3-pip ca-certificates curl
    elif command -v pacman >/dev/null 2>&1; then
        run_root pacman -Sy --needed --noconfirm python python-pip ca-certificates curl
    else
        fail "установите Python 3.8+, venv, pip и curl через пакетный менеджер"
    fi
}

if ! command -v python3 >/dev/null 2>&1; then
    install_python
fi
command -v python3 >/dev/null 2>&1 || fail "python3 не найден после установки"
python3 -c 'import sys; assert sys.version_info >= (3, 8), "нужен Python 3.8+"' \
    || fail "версия Python должна быть 3.8 или новее"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
ARCHIVE="$TMP_DIR/med-roster.tar.gz"
URL="https://github.com/$REPO/archive/refs/heads/$REF.tar.gz"
if [ "$REF" != "master" ] && [ "$REF" != "main" ]; then
    URL="https://github.com/$REPO/archive/$REF.tar.gz"
fi

say "Загрузка med-roster ($REF)…"
if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$URL" -o "$ARCHIVE"
elif command -v wget >/dev/null 2>&1; then
    wget -qO "$ARCHIVE" "$URL"
else
    install_python
    curl -fsSL "$URL" -o "$ARCHIVE"
fi
tar -xzf "$ARCHIVE" -C "$TMP_DIR" || fail "не удалось распаковать архив"
SRC="$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
[ -n "$SRC" ] && [ -f "$SRC/app/main.py" ] || fail "в архиве не найдено приложение"

mkdir -p "$INSTALL_ROOT" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
cp -R "$SRC/app" "$APP_DIR/app"
cp "$SRC/run.py" "$SRC/requirements.txt" "$APP_DIR/"
cp "$SRC/packaging/linux/med-roster.svg" "$ICON_DIR/med-roster.svg"

if [ ! -x "$VENV/bin/python" ]; then
    if ! python3 -m venv "$VENV"; then
        install_python
        python3 -m venv "$VENV" || fail "не удалось создать virtualenv"
    fi
fi
say "Установка зависимостей Python…"
"$VENV/bin/python" -m pip install --disable-pip-version-check -r "$APP_DIR/requirements.txt"

cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
set -e
APP_DIR="$APP_DIR"
cd "\$APP_DIR"
exec "$VENV/bin/python" run.py
EOF
chmod +x "$LAUNCHER"

cat > "$DESKTOP_DIR/med-roster.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=МедГрафик: Поликлиника
Comment=Расчёт графиков сменности и табелей рабочего времени
Exec=$LAUNCHER
Icon=med-roster
Terminal=false
Categories=Office;Utility;
EOF
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi

say ""
say "Установка завершена. Запуск: med-roster"
say "Также программа доступна в меню приложений как «МедГрафик: Поликлиника»."
say "Если команда не найдена, добавьте $BIN_DIR в PATH или выполните: $LAUNCHER"
