# -*- coding: utf-8 -*-
"""
Лаунчер приложения «МедГрафик: Поликлиника».

Запускает веб-сервер и открывает браузер на http://127.0.0.1:25625.

Используется:
  * напрямую — ``python run.py``;
  * сборкой в один исполняемый файл (PyInstaller) — см. ``packaging/``.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import webbrowser

HOST = "127.0.0.1"
PORT = 25625


def _error_log_path() -> str:
    d = os.environ.get("MEDROSTER_LOG_DIR") or tempfile.gettempdir()
    return os.path.join(d, "med-roster-error.log")


def _ensure_stdio() -> None:
    """В GUI-сборке PyInstaller (``console=False``) потоки ``sys.stdout`` и
    ``sys.stderr`` равны ``None``. Uvicorn при настройке логгера вызывает
    ``sys.stdout.isatty()`` и падает с ``AttributeError`` — поэтому перед
    запуском перенаправляем отсутствующие потоки в ``os.devnull``.
    """
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _startup_error_message(exc: BaseException) -> str:
    """Сформировать сообщение, которое прямо называет причину сбоя запуска."""
    reason = str(exc).strip() or "без текстового описания"
    return (
        "Не удалось запустить «МедГрафик: Поликлиника».\n\n"
        "Причина: %s: %s\n\n"
        "Журнал: %s\n"
        "Python: %s"
    ) % (type(exc).__name__, reason, _error_log_path(), sys.version.split()[0])


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


def _check_existing_instance(host: str, port: int) -> bool:
    """Вернуть True, если на порту уже работает другой экземпляр med-roster.

    Стучится в ``/api/health`` уже запущенного сервера: если тот отвечает
    ``app == "med-roster"``, значит на порту крутится прежняя версия (например,
    0.3.0), и новый запуск упрётся в «address already in use». Позволяет
    показать понятное сообщение вместо трассировки uvicorn.
    """
    try:
        req = urllib.request.urlopen(
            "http://%s:%d/api/health" % (host, port), timeout=1.5)
        data = json.loads(req.read().decode("utf-8"))
        return data.get("app") == "med-roster"
    except Exception:
        # нет соединения / не наш сервис / таймаут — порт свободен или занят чужим
        return False


def _find_pids_on_port(port: int) -> "set":
    """Найти PID процессов, слушающих заданный TCP-порт. Вернуть множество."""
    pids = set()
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(
                ["netstat", "-aon"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if (":%d " % port) in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        try:
                            pids.add(int(parts[-1]))
                        except ValueError:
                            pass
        else:
            # Linux: ss, затем lsof
            if shutil.which("ss"):
                out = subprocess.check_output(
                    ["ss", "-tlnp"], text=True, stderr=subprocess.DEVNULL)
                for line in out.splitlines():
                    if (":%d " % port) in line:
                        m = re.search(r"pid=(\d+)", line)
                        if m:
                            pids.add(int(m.group(1)))
            elif shutil.which("lsof"):
                out = subprocess.check_output(
                    ["lsof", "-ti", "tcp:%d" % port],
                    text=True, stderr=subprocess.DEVNULL)
                for tok in out.split():
                    if tok.isdigit():
                        pids.add(int(tok))
    except Exception:
        pass
    return pids


def _stop_existing_instance(port: int) -> bool:
    """Завершить процесс(ы), слушающие порт. Вернуть True, если что-то убито."""
    pids = _find_pids_on_port(port)
    killed = False
    for pid in pids:
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               capture_output=True, check=False)
            else:
                os.kill(pid, signal.SIGTERM)
            killed = True
        except Exception:
            pass
    if killed:
        time.sleep(0.5)  # дать процессу освободить порт
    return killed


def _confirm_stop() -> bool:
    """Спросить пользователя, остановить ли уже запущенную версию. True = да."""
    message = ("«МедГрафик: Поликлиника» уже запущена.\n\n"
               "Остановить работающую версию и запустить эту?")
    try:
        if sys.platform == "win32":
            import ctypes
            result = ctypes.windll.user32.MessageBoxW(
                None, message, "МедГрафик: Поликлиника", 0x04)  # MB_YESNO
            return result == 6  # IDYES
    except Exception:
        pass
    # консольный режим (Linux / Windows из терминала)
    try:
        answer = input(message + " [y/N] ").strip().lower()
        return answer in ("y", "yes", "д", "да")
    except Exception:
        return False


def main() -> None:
    _ensure_stdio()
    if _check_existing_instance(HOST, PORT):
        # Уже запущена прежняя версия — предлагаем остановить её, чтобы новая
        # могла занять порт 25625.
        if not _confirm_stop():
            return
        _stop_existing_instance(PORT)
        if _check_existing_instance(HOST, PORT):
            _show_error(
                "Не удалось остановить работающую версию.\n\n"
                "Завершите процесс вручную (Диспетчер задач или stop.bat / "
                "stop.sh) и запустите программу снова.")
            return
    # Импорты выполняем внутри main(): ошибки зависимостей/статических файлов
    # в портативной сборке тоже попадают в понятное диалоговое сообщение.
    import uvicorn
    from app.main import app

    threading.Thread(target=_open_browser, daemon=True).start()
    # log_level="warning" — меньше шума; на слабом железе меньше накладных расходов.
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        tb = traceback.format_exc()
        try:
            with open(_error_log_path(), "a", encoding="utf-8") as f:
                f.write("\n==== %s ====\n%s\n" % (time.ctime(), tb))
        except Exception:
            pass
        _show_error(_startup_error_message(exc))
        # Не показываем второй технический диалог PyInstaller с traceback.
        raise SystemExit(1)
