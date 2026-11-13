# med-roster — User Guide

> [Русская версия](USAGE.ru.md)

How to install, launch and use **med-roster («МедГрафик: Поликлиника»)** to
calculate shift schedules and time sheets (OKUD 0504421 / T-13).

---

## 1. Requirements

- Python **3.8+** (works on Windows 7 and Linux Debian 11–13 / Ubuntu).
- No database, no Node.js, no Docker — the app is a single FastAPI process with
  a vanilla-JS web page and SQLite-free in-memory sessions.

## 2. Installation

1. Clone the repository (or copy the project folder).
2. Install the dependencies:

   **Windows**
   ```
   py -m pip install -r requirements.txt
   ```

   **Linux**
   ```
   python3 -m pip install -r requirements.txt
   ```

## 3. Launch

**Windows** — double-click `start.bat` (or run it from the command line).

**Linux**
```
chmod +x start.sh
./start.sh
```

Or manually:
```
python -m uvicorn app.main:app --host 127.0.0.1 --port 25625
```

The web panel opens at **http://127.0.0.1:25625**.

## 4. Interface

The panel has two tabs.

### 4.1. Production calendar

- Enter a **year** (1990–2050) and click **«Показать»** («Show»).
- A table shows, for each month: working days, shortened (pre-holiday) days and
  the monthly hour norm for the 30 / 33 / 36 / 39 / 40-hour weeks (Order
  № 588n).
- Below: the annual norm and the lists of public holidays and shortened days.
- A badge **«требует сверки»** («needs verification») appears for years outside
  the exact 2020–2027 range (future decrees are not yet known).

### 4.2. Import a schedule

1. Open the **«Импорт графика (.xls)»** tab.
2. Choose a `.xls` file (the «СГП №16» layout). The period is detected
   automatically from the header; you may also set the year/month explicitly.
3. Click **«Импортировать»** («Import»).

The app parses the file, classifies job titles, recalculates each employee's
hours and runs the validator (5 error types). After import you see:

- **Summary** — employees, days in month, errors, warnings.
- **Export buttons** — CSV, Т-13, ОКУД 0504421, schedule for signature.
- **Errors and warnings** — the validator's findings.
- **Employees** — an editable grid.
- **Tools** — auto-fill and copy schedule.

## 5. Editing the schedule

- **Click** any day cell to edit it. Enter an interval like `8-15,48` or a
  status code (`В`, `ОТ`, `Б`, `У`).
- **Enter** — save and move down; **Esc** — cancel.
- Hours, totals and validation are recalculated after every change.
- The bottom **traffic light** summarizes the state:
  - 🟢 **green** — no errors, ready to export;
  - 🟡 **yellow** — warnings only, can export;
  - 🔴 **red** — errors remain, fix them and export again.

## 6. Tools

### Auto-fill
Fill a person's empty cells with one shift:
1. Pick the employee and type the shift (e.g. `8-15,48`).
2. Check **«только рабочие дни»** («workdays only») to fill only calendar
   working days (otherwise all empty days, including weekends).
3. Click **«Заполнить»** («Fill»).

### Copy schedule («doctor ↔ nurse»)
1. Pick the source employee in **«Из»** («From») and the target in **«В»**
   («To»).
2. Click **«Скопировать график»** («Copy schedule»). The target's entire month
   is overwritten with the source's shifts.

## 7. Export

All forms open in a new browser tab / download as HTML or CSV:

| Button | Format | Purpose |
| --- | --- | --- |
| График (CSV) | `;`-separated CSV | corrected schedule for Excel |
| Табель Т-13 | printable HTML | time sheet Т-13 |
| Табель ОКУД 0504421 | printable HTML | budget-institution time sheet |
| График на подпись | printable HTML | schedule for approval («УТВЕРЖДАЮ» / «СОГЛАСОВАНО») |

> Print the HTML forms from the browser (Ctrl+P).

## 8. Data and privacy

- Personal data (152-FZ) stays **local only**. `.xls`/`.docx` source files are
  ignored by git (see `.gitignore`) and never leave your machine.
- Sessions are **in-memory**: closing the server discards them. Re-import the
  file to continue.

## 9. Tests

Each module has a standalone test (no pytest):
```
python tests/test_calendar_rf.py
python tests/test_time_parser.py
python tests/test_norm_calculator.py
python tests/test_xls_importer.py
python tests/test_conflict_checker.py
python tests/test_exporter.py
python tests/test_scheduler.py
```
