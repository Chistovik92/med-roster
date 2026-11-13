# -*- coding: utf-8 -*-
"""
Лаунчер приложения «МедГрафик: Поликлиника».

Запускает веб-сервер и открывает браузер на http://127.0.0.1:25625.

Используется:
  * напрямую — ``python run.py``;
  * сборкой в один исполняемый файл (PyInstaller) — см. ``packaging/``.
"""
import os
import sys
import tempfile
import threading
import time
import traceback
import webbrowser

import uvicorn

from app.main import app

HOST = "127.0.0.1"
PORT = 25625


def _error_log_path() -> str:
    d = os.environ.get("MEDROSTER_LOG_DIR") or tempfile.gettempdir()
    return os.path.join(d, "med-roster-error.log")


def _show_error(message: str) -> None:
    """Показать ошибку пользователю (для GUI-сборки без консоли — MessageBox)."""
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None, message, "МедГрафик: Поликлиника", 0x10)
            return
    except Exception:
        pass
    sys.stderr.write(message + "\n")


def _open_browser() -> None:
    """Открыть браузер после небольшой паузы (серверу нужно стартовать)."""
    time.sleep(1.2)
    try:
        webbrowser.open("http://%s:%d" % (HOST, PORT))
    except Exception:
        # отсутствие браузера/окружения не должно ронять сервер
        pass


def main() -> None:
    threading.Thread(target=_open_browser, daemon=True).start()
    # log_level="warning" — меньше шума; на слабом железе меньше накладных расходов.
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        tb = traceback.format_exc()
        try:
            with open(_error_log_path(), "a", encoding="utf-8") as f:
                f.write("\n==== %s ====\n%s\n" % (time.ctime(), tb))
        except Exception:
            pass
        _show_error("Не удалось запустить сервер.\n\nПодробности: %s" % _error_log_path())
        raise
