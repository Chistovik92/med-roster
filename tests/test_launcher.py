# -*- coding: utf-8 -*-
"""Проверка понятной диагностики запуска портативной сборки."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run


def main():
    message = run._startup_error_message(ImportError("DLL load failed while importing _socket"))
    assert "ImportError" in message
    assert "DLL load failed while importing _socket" in message
    assert "Причина:" in message
    assert "Журнал:" in message
    assert "Python:" in message
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "packaging", "medgrafik.spec"), encoding="utf-8") as f:
        spec = f.read()
    assert "ucrtbase.dll" in spec
    assert 'os.path.join(_ucrt_dir, "*.dll")' in spec
    print("OK  диагностика запуска и включение UCRT для Windows 7")


if __name__ == "__main__":
    main()
