# -*- coding: utf-8 -*-
"""Проверка обновлений без обращения к внешней сети."""
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import __version__
from app.services import updater


def test_app_status(monkeypatch):
    monkeypatch.setattr(updater, "_json_url", lambda url: {
        "tag_name": "v99.0.0", "html_url": "https://example.test/release"
    })
    status = updater.app_status()
    assert status["current"] == __version__
    assert status["latest"] == "99.0.0"
    assert status["available"] is True


def test_safe_extract():
    tmp = tempfile.mkdtemp(prefix="med-roster-update-test-")
    archive = os.path.join(tmp, "update.zip")
    target = os.path.join(tmp, "files")
    os.makedirs(target)
    with zipfile.ZipFile(archive, "w") as zf:
        for name in ("MedGrafik.exe", "_socket.pyd", "ucrtbase.dll", "app/static/index.html"):
            zf.writestr(name, b"test")
    updater._safe_extract(archive, target)
    assert os.path.isfile(os.path.join(target, "MedGrafik.exe"))


def test_safe_extract_rejects_path_traversal():
    tmp = tempfile.mkdtemp(prefix="med-roster-update-test-")
    bad = os.path.join(tmp, "bad.zip")
    target = os.path.join(tmp, "files")
    os.makedirs(target)
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../bad", b"bad")
    try:
        updater._safe_extract(bad, target)
    except ValueError:
        pass
    else:
        raise AssertionError("небезопасный путь архива должен отклоняться")
