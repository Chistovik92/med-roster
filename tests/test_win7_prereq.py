# -*- coding: utf-8 -*-
"""Проверка комплектации KB2533623 и контроля целостности."""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import win7_prereq


def test_msu_present_and_sha256():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for arch, expected in win7_prereq.KB2533623_SHA256.items():
        path = os.path.join(root, "packaging", "windows",
                            win7_prereq.KB2533623_FILES[arch])
        assert os.path.isfile(path), "MSU должен быть в репозитории: " + path
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest().upper()
        assert digest == expected, (arch, digest)


def test_has_kb2533623_not_windows7():
    assert win7_prereq.has_kb2533623() is True  # не Windows 7 → True


def test_spec_and_workflow_reference_msu():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "packaging", "medgrafik.spec"), encoding="utf-8") as f:
        spec = f.read()
    assert "Windows6.1-KB2533623-x86.msu" in spec
    assert "Windows6.1-KB2533623-x64.msu" in spec

    workflow_path = os.path.join(root, ".github", "workflows", "release.yml")
    if os.path.isfile(workflow_path):
        with open(workflow_path, encoding="utf-8") as f:
            workflow = f.read()
        assert "Windows6.1-KB2533623-x64.msu" in workflow
