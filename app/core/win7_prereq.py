# -*- coding: utf-8 -*-
"""Проверка обязательного системного обновления KB2533623 на Windows 7."""
import ctypes
import hashlib
import os
import subprocess
import sys


KB2533623_SHA256 = {
    "x86": "43BE36D164FD1C0CFF8E45BFB318EFA904EC4B53B0C8D306ABD640F1C06CCC41",
    "x64": "58B8B00113FA8B9657D8DA5B14BAE93F765F29651C81055E3D127D4A22E5C0D6",
}
KB2533623_FILES = {
    "x86": "Windows6.1-KB2533623-x86.msu",
    "x64": "Windows6.1-KB2533623-x64.msu",
}


def _is_windows7() -> bool:
    return sys.platform == "win32" and sys.getwindowsversion().major == 6 and sys.getwindowsversion().minor == 1


def has_kb2533623() -> bool:
    """True, если SetDefaultDllDirectories доступна (KB2533623 или новее)."""
    if not _is_windows7():
        return True
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        return hasattr(kernel32, "SetDefaultDllDirectories")
    except Exception:
        return False


def ensure_kb2533623() -> bool:
    """Установить KB2533623 при необходимости. Вернуть True, если доступен."""
    if has_kb2533623():
        return True

    if sys.platform != "win32":
        return True

    # Определяем разрядность ОС через SYSTEM_* (не через pointer size).
    arch = "x86"
    try:
        import platform
        arch = "x64" if platform.machine().lower() in ("amd64", "x86_64") else "x86"
    except Exception:
        pass

    filename = KB2533623_FILES[arch]
    msu = os.path.join(os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
                       else os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       filename)
    if not os.path.isfile(msu):
        return False

    with open(msu, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest().upper()
    if digest != KB2533623_SHA256[arch]:
        return False

    try:
        proc = subprocess.run(["wusa.exe", msu, "/quiet", "/norestart"],
                              timeout=300, check=False)
        # 3010 — установлено, нужна перезагрузка.
        if proc.returncode in (0, 3010):
            return has_kb2533623() or proc.returncode == 3010
    except Exception:
        pass
    return False


def check_and_prompt() -> None:
    """GUI-загрузчик: установить KB и показать понятное сообщение при ошибке."""
    if _is_windows7() and not has_kb2533623():
        ok = ensure_kb2533623()
        if not ok:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                "Для запуска требуется обновление Windows 7 KB2533623.\n\n"
                "Файл включён в комплект, но автоматическая установка не удалась.\n"
                "Запустите Windows6.1-KB2533623-x64.msu (или -x86.msu) вручную\n"
                "и перезагрузите компьютер.",
                "МедГрафик: Поликлиника", 0x10)
            raise SystemExit(1)
