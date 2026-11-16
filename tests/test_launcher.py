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
    print("OK  сообщение запуска содержит тип, причину, журнал и версию Python")


if __name__ == "__main__":
    main()
