# -*- mode: python ; coding: utf-8 -*-
# Spec для сборки «МедГрафик: Поликлиника» в автономное приложение (PyInstaller).
#
# Результат — папка ``dist/MedGrafik`` с ``MedGrafik.exe`` (onedir: быстрее
# стартует на слабом железе, чем onefile, т.к. не распаковывается во временную
# папку). Эту папку NSIS-установщик упаковывает в один ``MedGrafik-Setup-*.exe``.
#
# Запуск:  pyinstaller packaging/medgrafik.spec
import os

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Корень репозитория (spec лежит в packaging/).
ROOT = os.path.dirname(os.path.abspath(SPECPATH))

hiddenimports = []
for _pkg in ("uvicorn", "pydantic", "fastapi", "starlette"):
    try:
        hiddenimports += collect_submodules(_pkg)
    except Exception:
        pass

datas = []
# Статические файлы фронтенда (index.html, app.js, style.css).
datas += [(os.path.join(ROOT, "app", "static"), "app/static")]
for _pkg in ("fastapi", "starlette", "uvicorn"):
    try:
        datas += collect_data_files(_pkg)
    except Exception:
        pass

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "unittest", "pytest", "numpy", "matplotlib", "pandas",
        "PIL", "IPython", "jedi", "notebook", "scipy",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MedGrafik",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX может ломать python DLL на старых ОС — не используем
    console=False,      # GUI-приложение без консольного окна
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MedGrafik",
)
