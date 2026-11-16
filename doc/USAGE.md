# med-roster — User Guide

> [Русская версия](USAGE.ru.md)

How to install, launch and use **med-roster («МедГрафик: Поликлиника»)** to
calculate shift schedules and time sheets (OKUD 0504421 / T-13).

---

## 1. Requirements

- Python **3.8+** (works on Windows 7 and Linux Debian 11–13 / Ubuntu).
- No Node.js, no Docker — the app is a single FastAPI process with a vanilla-JS
  web page. Saved months live in a local SQLite database (Python's built-in
  `sqlite3`, no extra dependencies).

> **Installers:** to avoid installing Python manually, grab a ready installer from
> the [GitHub release](https://github.com/Chistovik92/med-roster/releases): `.exe`
> for Windows, `.deb`/`.rpm` for Linux.

## 2. Installation

### Option A — ready installer (recommended)

- **Windows:** run `MedGrafik-Setup-<version>.exe` — installs into your user
  profile; shortcuts appear in the Start menu and on the Desktop.
- **Debian/Ubuntu:** `sudo dpkg -i med-roster_<version>_amd64.deb` (internet is
  needed at install time for dependencies).
- **Fedora/Simply Linux:** `sudo rpm -i med-roster-<version>.x86_64.rpm`.

**Linux — install or update directly from the repository with one command:**

```bash
curl -fsSL https://raw.githubusercontent.com/Chistovik92/med-roster/master/install.sh | bash
```

Then launch `med-roster` or use the application menu entry. The script downloads
the code, creates a virtualenv and installs dependencies. If Python is missing,
it can install the required system packages via `sudo` on supported distributions.

### Option B — run from source

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

> **Re-launching.** The app occupies port 25625, so you can't run a second copy
> (or a new version) at the same time. If a launch reports that the service is
> already running, stop the running copy (see section 11) and start again. The
> `run.py` launcher detects a running copy and offers to stop it and continue.

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

### 4.2. The «График» tab — data source

The «График» tab combines four ways to start:

1. **Import .xls** — choose a `.xls` file (the «СГП №16» layout) and click
   **«Импортировать»** («Import»). The period is detected from the header
   automatically (year/month may also be set explicitly).
2. **New schedule manually** — set the year and month and click **«Создать»**
   («Create»): you get an empty schedule to fill with employees and cells
   (see section 5).
3. **Saved months** — the list of previously saved schedules: «Загрузить»
   («Load») opens one, «Удалить» («Delete») removes it from the list.
4. **Generate the next month** — builds a schedule for the given month from the
   current one: it carries over the employee roster, and (when the checkbox
   «перенести смены по дням недели» is on) also the shifts themselves — for each
   weekday the most frequent shift is taken.

The app parses/loads/generates, classifies job titles, recalculates hours and
runs the validator (5 error types). After that you see:

- **Summary** — period, employees, days in month, errors, warnings.
- **Export and save buttons** — «Сохранить месяц» («Save month»), CSV, Т-13,
  ОКУД 0504421, schedule for signature.
- **Errors and warnings** — the validator's findings (including for manual data).
- **Employees** — an editable grid (add/remove employees).
- **Tools** — auto-fill and copy schedule.

### 4.3. Institution and department

The header fields **«Учреждение»** («Institution») and **«Подразделение»**
(«Department») are inserted into XLS and printable forms (Т-13, ОКУД 0504421,
schedule for signature) and remembered by the browser (`localStorage`). The
department is also stored with each saved month. Default institution —
«ГУЗ «СГП № 16»».

## 5. Editing the schedule

**The grid opens immediately at startup**: an empty schedule for the current
month is created automatically, so you can start entering data right away. To
use another month or data source (`.xls` import, a saved month, generation),
select it in the «Источник данных» card above.

- **Compact view.** Data sources, summary, errors and tools are collapsible; the
  grid uses the available window space. The month fits standard monitor widths;
  when horizontal scrolling is still needed, names and job titles stay pinned.
- **Day headings** show the weekday and date («Пн 1», «Вт 2»…). Weekends and
  public holidays have a grey background; shortened pre-holiday days have a
  green underline.
- **Error location and reason.** Invalid cells are highlighted and the employee,
  day and reason appear above the grid. Clicking an item in the errors/warnings
  list jumps to the corresponding cell or row.
- **«Исправить ошибки автоматически»** («Correct errors automatically») recalculates
  the norm, aligns hour totals, removes exact duplicates and shortens detected
  pre-holiday shifts by one hour. Overlapping rates and unknown job titles remain
  manual; review the schedule after correction.
- **Click** a day cell to edit it. A **large floating field** (400×180px, 24px
  bold font) opens next to the cell — the value is fully visible while the month
  table stays on screen. Enter saves and moves down, Tab moves right, Esc cancels.
- **Hotkeys.** When a cell is selected but its input field is not open: **1** —
  morning shift, **2** — evening shift (duration depends on the employee's week
  norm), **В** — day off, **О** — vacation, **Б** — sick leave, **У** — study.
  **Enter**/**F2** opens manual input; **arrow keys** navigate between cells.
- In the input field, **Enter** saves and moves down, **Tab** saves and moves
  right, and **Esc** cancels.
- **Click** a name, job title, rate or week norm to change it. The rate
  (1,00 / 0,75 / 0,50 / 0,25) and the week norm are picked from a list. When the
  job title changes, the norm is re-classified automatically (and can be set
  manually).
- To add an employee, fill «Ф.И.О.», «Должность», «Ставка» and click
  **«Добавить сотрудника»**. Remove a row with the «✕» button on the right.
- **«Добавить списком…»** lets you paste several lines in the format
  «name; job title; rate» (the rate is optional and defaults to 1.00), then add
  everyone at once with **«Добавить всех»**.
- Hours, totals and validation are recalculated after every change. For
  manually-entered rows the month norm is computed automatically (Order № 588n)
  and compared with the actual hours.
- The bottom **traffic light** summarizes the state:
  - 🟢 **green** — no errors, ready to export;
  - 🟡 **yellow** — warnings only, can export;
  - 🔴 **red** — errors remain, fix them and export again.

## 6. Saving and generating months

### Saving a month
Click **«Сохранить месяц»** («Save month») in the summary. The schedule is
written to a local SQLite database:

- Windows / Linux portable and installed — **inside the program folder**;
- source launch — the user data directory
  (`%APPDATA%\med-roster` / `~/.local/share/med-roster`);
- override — the `MEDROSTER_DATA_DIR` environment variable.

In «Сохранённые месяцы» you can **rename** a month, **«Сохранить базу (копия)»**
to export the whole `med-roster.db` to a chosen location, and **«Подгрузить базу»**
to merge a previously exported database (no duplicates).

### Generating the next months
1. Open / create / load a schedule (e.g. for November).
2. In the «Сгенерировать следующий месяц» block set the year and month and turn
   the «перенести смены по дням недели» checkbox on or off.
3. Click **«Сгенерировать»** («Generate») — a schedule for the new month appears
   with the same employee roster. Check it and save.

## 7. Tools

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

## 8. Export

Forms download as XLS, CSV or printable HTML:

| Button | Format | Purpose |
| --- | --- | --- |
| График (.xls) | binary Excel `.xls` | corrected schedule; can be imported again |
| График (CSV) | `;`-separated CSV | corrected schedule for Excel |
| Табель Т-13 | printable HTML | time sheet Т-13 |
| Табель ОКУД 0504421 | printable HTML | budget-institution time sheet |
| График на подпись | printable HTML | schedule for approval («УТВЕРЖДАЮ» / «СОГЛАСОВАНО») |

> Print the HTML forms from the browser (Ctrl+P).

## 9. Data and privacy

- Personal data (152-FZ) stays **local only**. `.xls`/`.docx` source files are
  ignored by git (see `.gitignore`) and never leave your machine.
- The current session is **in-memory**: closing the server discards it. To keep
  working later, click **«Сохранить месяц»** and then load the saved month.

## 10. Tests

Each module has a standalone test (no pytest):
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

## 11. Updates and required components

Click **«Обновления»** («Updates») in the top-right area, then **«Проверить
обновления»** («Check for updates»). The app shows its current/latest GitHub
version and the state of required components. Internet access is required.

- **Windows portable / installed:** when a release is available, click
  «Установить обновление». The official ZIP is downloaded and checked for the
  executable, `_socket.pyd`, UCRT and UI files. The service stops, files are
  replaced and the app restarts. Python and UCRT do not need separate installs.
- **Linux:** the update runs the standard `install.sh` and restarts the app.
- **Source launch:** «Обновить компоненты» installs compatible packages through
  pip and `requirements.txt`. Restart the application afterwards.

## 12. Stopping the service

The app runs as a background web server on port 25625. To stop it cleanly (for
example, before launching a new version):

- **The «Выключить сервис» («Shut down service») button** in the top-right corner
  of the panel — the simplest way. A «Сервис остановлен» screen appears and you
  can close the tab.
- **`stop.bat`** (Windows) — double-click to stop the process listening on port
  25625.
- **`stop.sh`** (Linux) — `./stop.sh` (uses `fuser`, falling back to `lsof`).

If an old version is running without the «Выключить» button, use `stop.bat` /
`stop.sh` — they work with any version.

> **Why this matters.** A new version cannot take port 25625 while an old one is
> still running, so stop the old copy before launching an update. Since 0.4.5 the
> launcher handles this automatically: it detects the running copy and offers to
> stop it in one step.
