# med-roster — "MedGraphic: Polyclinic"

> [Русская версия](README.ru.md)

Automation of shift scheduling and time-sheet calculation (OKUD 0504421 / T-13)
for all staff categories of the children's and adult polyclinic of
State Healthcare Institution "SGP № 16".

The program imports real schedules from `.xls` files ("SGP №16" format), detects
errors in them, lets you correct them right in the browser, and exports finished
official forms.

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
- **In-browser editing**: click a cell, Enter to save, Esc to cancel; auto-fill
  shifts and copy schedules ("doctor ↔ nurse"); bottom "traffic light"
  (green/yellow/red).
- **Export**: corrected schedule (CSV) and printable forms — T-13, OKUD 0504421,
  schedule for approval/signature.

## Requirements

- Python **3.8+** (works on Windows 7 and Linux Debian 11–13 / Ubuntu).
- Dependencies from `requirements.txt` (`fastapi`, `uvicorn`, `pydantic`,
  `python-multipart`, `xlrd`).

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

A browser opens at `http://127.0.0.1:8000`.

Manually:

```
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Structure

```
app/
  core/          # Russian production calendar, constants
  services/      # time parser, norms, import, validator, export, scheduler
  static/        # frontend (vanilla JS, no React/Node)
  main.py        # FastAPI application
tests/           # regression tests (run: python tests/test_*.py)
start.bat        # Windows launcher
start.sh         # Linux launcher
requirements.txt
AGENTS.md        # project memory (decisions, formulas, data)
ARCHITECTURE.md  # project passport (references, norms, architecture, UX, roadmap)
```

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
```

> `.xls` files containing personal data of employees are **not** committed to the
> repository (see `.gitignore`) — import/validator tests are skipped when they are
> absent.

## Notes

- Personal data (152-FZ) stays local only and is never committed to git.
- Docker is optional (for a modern Linux server), not required.
