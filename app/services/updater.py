# -*- coding: utf-8 -*-
"""Проверка и установка обновлений приложения и его Python-компонентов."""
from __future__ import annotations

import io
import json
import os
import platform
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from importlib import metadata
from typing import Dict, List

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from app import __version__

GITHUB_RELEASE_API = "https://api.github.com/repos/Chistovik92/med-roster/releases/latest"
DEPENDENCIES = (
    "fastapi", "uvicorn", "pydantic", "python-multipart", "xlrd", "xlwt", "packaging",
)
TIMEOUT = 12


def _json_url(url: str) -> Dict:
    req = urllib.request.Request(url, headers={"User-Agent": "med-roster-updater"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _release_version(tag: str) -> str:
    return (tag or "").lstrip("vV")


def app_status() -> Dict:
    """Статус приложения; сбой сети возвращается текстом, без падения UI."""
    result = {"current": __version__, "latest": __version__,
              "available": False, "url": "", "error": ""}
    try:
        release = _json_url(GITHUB_RELEASE_API)
        latest = _release_version(release.get("tag_name", ""))
        Version(latest)  # проверяем формат до использования в имени архива
        result.update({"latest": latest,
                       "available": Version(latest) > Version(__version__),
                       "url": release.get("html_url", "")})
    except Exception as exc:  # сеть/GitHub недоступны — показываем причину
        result["error"] = str(exc)
    return result


def _installed_version(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "не установлен"


def _latest_compatible(package: str) -> str:
    data = _json_url("https://pypi.org/pypi/%s/json" % package)
    python = platform.python_version()
    candidates = []
    for raw, files in (data.get("releases") or {}).items():
        try:
            version = Version(raw)
        except InvalidVersion:
            continue
        if version.is_prerelease or not files:
            continue
        usable = False
        for item in files:
            if item.get("yanked"):
                continue
            requires = item.get("requires_python") or ""
            try:
                if not requires or SpecifierSet(requires).contains(python):
                    usable = True
                    break
            except Exception:
                continue
        if usable:
            candidates.append(version)
    return str(max(candidates)) if candidates else data.get("info", {}).get("version", "")


def dependencies_status() -> List[Dict]:
    result = []
    for package in DEPENDENCIES:
        current = _installed_version(package)
        item = {"name": package, "current": current,
                "latest": "", "available": False, "error": ""}
        try:
            latest = _latest_compatible(package)
            item["latest"] = latest
            item["available"] = (current != "не установлен" and bool(latest)
                                 and Version(latest) > Version(current))
            if current == "не установлен":
                item["available"] = bool(latest)
        except Exception as exc:
            item["error"] = str(exc)
        result.append(item)
    return result


def maintenance_status() -> Dict:
    frozen = bool(getattr(sys, "frozen", False))
    return {
        "app": app_status(),
        "dependencies": dependencies_status(),
        "frozen": frozen,
        "platform": sys.platform,
        "can_self_update": (frozen and sys.platform == "win32") or
                           (not frozen and sys.platform.startswith("linux")),
        "can_update_dependencies": not frozen,
        "python": platform.python_version(),
    }


def update_dependencies() -> Dict:
    """Обновить прямые зависимости; pip сам выбирает совместимые версии."""
    if getattr(sys, "frozen", False):
        return {"ok": False, "error": "В portable компоненты обновляются вместе с программой"}
    requirements = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "requirements.txt")
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "-r", requirements]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    return {"ok": proc.returncode == 0, "output": output[-5000:],
            "error": "" if proc.returncode == 0 else "pip завершился с ошибкой"}


def _safe_extract(archive: str, target: str) -> None:
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            normalized = name.replace("\\", "/")
            if normalized.startswith("/") or ".." in normalized.split("/"):
                raise ValueError("Небезопасный путь в архиве обновления")
        names = set(zf.namelist())
        required = {"MedGrafik.exe", "_socket.pyd", "ucrtbase.dll",
                    "app/static/index.html"}
        missing = required - names
        if missing:
            raise ValueError("В архиве нет: %s" % ", ".join(sorted(missing)))
        zf.extractall(target)


def install_windows_update() -> Dict:
    """Скачать release ZIP и запустить внешнюю замену после выхода процесса."""
    if not (getattr(sys, "frozen", False) and sys.platform == "win32"):
        return {"ok": False, "error": "Самообновление доступно в Windows-сборке"}
    status = app_status()
    if not status["available"]:
        return {"ok": False, "error": "Новая версия не найдена или уже установлена"}

    release = _json_url(GITHUB_RELEASE_API)
    version = status["latest"]
    asset_name = "MedGrafik-portable-%s-win32.zip" % version
    asset = next((a for a in release.get("assets", [])
                  if a.get("name") == asset_name), None)
    if asset is None:
        return {"ok": False, "error": "В релизе нет %s" % asset_name}

    work = tempfile.mkdtemp(prefix="med-roster-update-")
    archive = os.path.join(work, asset_name)
    source = os.path.join(work, "files")
    os.makedirs(source, exist_ok=True)
    req = urllib.request.Request(asset["browser_download_url"],
                                 headers={"User-Agent": "med-roster-updater"})
    with urllib.request.urlopen(req, timeout=120) as response, open(archive, "wb") as out:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
    _safe_extract(archive, source)

    target = os.path.dirname(os.path.abspath(sys.executable))
    script = os.path.join(work, "install-update.ps1")
    with io.open(script, "w", encoding="utf-8") as f:
        f.write(
            "param([int]$ProcessId, [string]$Source, [string]$Target, [string]$Exe)\n"
            "Wait-Process -Id $ProcessId -ErrorAction SilentlyContinue\n"
            "Start-Sleep -Seconds 1\n"
            "Copy-Item -Path (Join-Path $Source '*') -Destination $Target -Recurse -Force\n"
            "Start-Process -FilePath $Exe -WorkingDirectory $Target\n"
        )
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", script, "-ProcessId", str(os.getpid()), "-Source", source,
        "-Target", target, "-Exe", os.path.abspath(sys.executable),
    ], cwd=work, close_fds=True, creationflags=flags,
       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    return {"ok": True, "version": version,
            "message": "Обновление установится после закрытия сервиса; программа перезапустится"}


def install_linux_update() -> Dict:
    """Обновить Linux-установку штатным install.sh после завершения сервиса."""
    if getattr(sys, "frozen", False) or not sys.platform.startswith("linux"):
        return {"ok": False, "error": "Этот способ обновления предназначен для Linux"}
    status = app_status()
    if not status["available"]:
        return {"ok": False, "error": "Новая версия не найдена или уже установлена"}
    work = tempfile.mkdtemp(prefix="med-roster-update-")
    script = os.path.join(work, "install-update.sh")
    with io.open(script, "w", encoding="utf-8") as f:
        f.write("""#!/usr/bin/env bash
while kill -0 "$1" 2>/dev/null; do sleep 1; done
curl -fsSL https://raw.githubusercontent.com/Chistovik92/med-roster/master/install.sh | bash || exit 1
nohup "$HOME/.local/bin/med-roster" >/dev/null 2>&1 &
""")
    subprocess.Popen(["/bin/bash", script, str(os.getpid())],
                     cwd=work, close_fds=True, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL)
    return {"ok": True, "version": status["latest"],
            "message": "Linux-установка обновится после закрытия сервиса; программа перезапустится"}


def install_app_update() -> Dict:
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        return install_windows_update()
    if not getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
        return install_linux_update()
    return {"ok": False, "error": "Автоустановка недоступна; скачайте релиз с GitHub"}
