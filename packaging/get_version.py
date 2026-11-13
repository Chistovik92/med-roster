#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вывести версию проекта (из app/__init__.py) в stdout.

Используется скриптами сборки (build_windows.bat, build_linux.sh, CI), чтобы
не дублировать версию. Не требует сторонних зависимостей.
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

with io.open(os.path.join(ROOT, "app", "__init__.py"), encoding="utf-8") as f:
    text = f.read()

m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
if not m:
    sys.stderr.write("Не удалось определить __version__ в app/__init__.py\n")
    sys.exit(1)

print(m.group(1))
