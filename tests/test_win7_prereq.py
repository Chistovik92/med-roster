# -*- coding: utf-8 -*-
"""Проверка комплектации KB2533623 и контроля целостности."""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import win7_prereq


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for arch, expected in win7_prereq.KB2533623_SHA256.items():
        path = os.path.join(root, "packaging", "windows",
                            win7_prereq.KB2533623_FILES[arch])
        assert os.path.isfile(path), "MSU должен быть в репозитории: " + path
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest().upper()
        assert digest == expected, (arch, digest)

    assert win7_prereq.has_kb2533623() is True  # не Windows 7 → True
    spec = open(os.path.join(root, "packaging", "medgrafik.spec"), encoding="utf-8").read()
    assert "Windows6.1-KB2533623-x86.msu" in spec
    assert "Windows6.1-KB2533623-x64.msu" in spec
    workflow = open(os.path.join(root, ".github", "workflows", "release.yml"),
                    encoding="utf-8").read()
    assert "Windows6.1-KB2533623-x64.msu" in workflow
    print("OK  KB2533623 x86+x64 в комплекте, SHA256 совпадает, spec/workflow проверяют")


if __name__ == "__main__":
    main()
