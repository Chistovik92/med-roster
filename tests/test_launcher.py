# -*- coding: utf-8 -*-
"""Проверка понятной диагностики запуска портативной сборки."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run


def test_startup_error_message():
    message = run._startup_error_message(ImportError("DLL load failed while importing _socket"))
    assert "ImportError" in message
    assert "DLL load failed while importing _socket" in message
    assert "Причина:" in message
    assert "Журнал:" in message
    assert "Python:" in message


def test_spec_includes_ucrt():
    spec_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "packaging", "medgrafik.spec")
    with open(spec_path, encoding="utf-8") as f:
        spec = f.read()
    assert "ucrtbase.dll" in spec
    assert 'os.path.join(_ucrt_dir, "*.dll")' in spec
