# med-roster — "MedGraphic: Polyclinic"

> [Русская версия](README.ru.md)

Automation of shift scheduling and time-sheet calculation (OKUD 0504421 / T-13)
for all staff categories of the children's and adult polyclinic of
State Healthcare Institution "SGP № 16".

The program imports real schedules from `.xls` files ("SGP №16" format), detects
errors in them, lets you correct them right in the browser, and exports finished
official forms.

## Releases / installers

Prebuilt installers are attached to each [GitHub release](https://github.com/Chistovik92/med-roster/releases):

| System | Installer |
| --- | --- |
| Windows 7 / 10 / 11 (x86/x64) | `MedGrafik-Setup-<ver>.exe` (or portable `win32.zip`) |
| Debian / Ubuntu | `med-roster_<ver>_amd64.deb` |
| Fedora / Simply Linux and others | `med-roster-<ver>.x86_64.rpm` |
| Any Linux | `med-roster-<ver>.tar.gz` (portable) |

Installers are built automatically by GitHub Actions (see `.github/workflows/release.yml`
and `packaging/`).

### Linux — one-command installation

```bash
curl -fsSL https://raw.githubusercontent.com/Chistovik92/med-roster/master/install.sh | bash
```

The installer uses `~/.local/share/med-roster`, creates a virtualenv, an application
menu entry and the `med-roster` launch command. Run the same command again to update;
saved months are preserved.

## Features

- **Russian production calendar** for any year (1990–2050), including holiday
  transfers, pre-holiday shortened days and "working Saturdays". Exact for
  2020–2027.
- **Working-time norm calculation** per Order № 588n for weekly norms of
  30/33/36/39/40 hours and part-time rates (1.0 / 0.75 / 0.5 / 0.25), with
  absence deduction.
- **`.xls` import** (xlrd) with automatic period detection and job-title
  classification.
- **Validator for 5 error types** (verified on real data):
  1. wrong monthly norm in the "Прим." column;
  2. overlapping shifts for one person (full-time + 0.5/0.75 rate);
  3. missing pre-holiday day shortening;
  4. duplicate rows;
  5. hour-total mismatches.
- **In-browser editing**: the grid opens right at startup (empty schedule for the
  current month); click a cell, Enter to save and move down, Tab to move right,
  Esc to cancel; arrow-key navigation; hotkeys `1`/`2` (preset shifts) and
  `В`/`О`/`Б`/`У` (status codes); weekend/pre-holiday highlighting; auto-fill
  shifts and copy schedules ("doctor ↔ nurse"); bulk-adding employees from a
  list; bottom "traffic light" (green/yellow/red).
- **Automatic correction** of norms, hour totals, exact duplicates and shortened
  pre-holiday shifts; ambiguous overlapping rates remain manual.
- **Department field** in the UI, saved months, XLS and printable forms.
- **Update centre**: GitHub release and Python dependency checks, in-app updates
  for portable/installed Windows and Linux with automatic restart.
- **Large cell editor** (400×180px, 24px bold font) and a months database:
  save/update/rename months, export the whole database to a chosen location, and
  import an external database.
- **Export**: corrected schedule (XLS and CSV) and printable forms — T-13, OKUD 0504421,
  schedule for approval/signature.

## Requirements

- Python **3.8+** (works on Windows 7 and Linux Debian 11–13 / Ubuntu).
- Dependencies from `requirements.txt` (`fastapi`, `uvicorn`, `pydantic`,
  `python-multipart`, `xlrd`, `xlwt`, `packaging`).

## Quick start

Windows:

```
start.bat
```

Linux:

```
chmod +x start.sh
./start.sh
```

A browser opens at `http://127.0.0.1:25625`.

Manually:

```
python -m uvicorn app.main:app --host 127.0.0.1 --port 25625
```

## Structure

```
app/
  core/          # Russian production calendar, constants
  services/      # time parser, norms, import, validator, export, scheduler
  static/        # frontend (vanilla JS, no React/Node)
  main.py        # FastAPI application
run.py           # launcher (server + browser; used by PyInstaller too)
tests/           # regression tests (run: python tests/test_*.py)
packaging/       # installers: PyInstaller spec, NSIS, fpm, CI workflow
doc/
  USAGE.md       # user guide (English)
  USAGE.ru.md    # user guide (Russian)
  ARCHITECTURE.md  # project passport (references, norms, architecture, UX, roadmap)
start.bat        # Windows launcher
start.sh         # Linux launcher
install.sh       # one-command Linux installer/updater
requirements.txt
CHANGELOG.md
AGENTS.md        # project memory (decisions, formulas, data)
```

## Documentation

- **[User guide (English)](doc/USAGE.md)** and
  **[Инструкция пользователя (русский)](doc/USAGE.ru.md)** — how to install,
  launch and use the program.
- **[ARCHITECTURE.md](doc/ARCHITECTURE.md)** — project passport (references,
  normative base, norm matrix, architecture, UX, roadmap).

## Tests

Each module has a standalone test (no pytest needed):

```
python tests/test_calendar_rf.py
python tests/test_time_parser.py
python tests/test_norm_calculator.py
python tests/test_xls_importer.py
python tests/test_conflict_checker.py
python tests/test_exporter.py
python tests/test_scheduler.py
python tests/test_storage.py
python tests/test_shutdown.py
python tests/test_bulk_and_meta.py
python tests/test_launcher.py
python tests/test_ui.py
python tests/test_autocorrect.py
python tests/test_xls_export.py
python tests/test_updater.py
```

> `.xls` files containing personal data of employees are **not** committed to the
> repository (see `.gitignore`) — import/validator tests are skipped when they are
> absent.

## Notes

- Personal data (152-FZ) stays local only and is never committed to git.
- Docker is optional (for a modern Linux server), not required.
