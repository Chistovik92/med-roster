# med-roster — API для интеграции со сторонними программами

> **Версия:** 0.6.4+  
> **Базовый URL:** `http://127.0.0.1:25625` (локально)  
> **Формат:** JSON (запросы/ответы), файловые форматы для экспорта

---

## 1. Общие принципы

| Аспект | Детали |
|--------|--------|
| **Авторизация** | Отсутствует (локальный сервис, single-user). Для сети — положите за reverse proxy с auth. |
| **Сессии** | In-memory (`_sessions` dict, TTL 30 мин, макс. 8 одновременных). `session_id` возвращается при создании/импорте. |
| **Идентификаторы строк** | `row.index` — порядковый номер (0-based) из исходного файла/создания. Не меняется при редактировании. |
| **Дни месяца** | 1-based (1…31). В JSON ключи дней — строки `"1"`, `"2"`… |
| **Коды ошибок** | `400` — плохой запрос, `404` — сессия/запись не найдена, `422` — ошибка валидации, `500` — внутренняя. |

---

## 2. Справочные эндпоинты (без сессии)

### `GET /api/health`
Проверка живости сервиса.

**Ответ:**
```json
{ "status": "ok", "app": "med-roster", "version": "0.6.4" }
```

### `GET /api/calendar/{year}`
Производственный календарь РФ на год + нормы часов по неделям.

**Параметры:** `year` (int, 1990–2040+)

**Ответ:**
```json
{
  "year": 2026,
  "need_verify": false,
  "months": [
    { "month": 1, "work": 15, "short": 0, "norm": { "30": 119, "33": 131, "36": 143, "39": 155, "40": 159 } },
    ...
  ],
  "year_norm": { "30": 1428, "33": 1562, "36": 1701, "39": 1836, "40": 1881 },
  "short_days": [{ "month": 4, "day": 30 }, { "month": 5, "day": 8 }, ...],
  "holidays": [{ "month": 1, "day": 1 }, { "month": 1, "day": 2 }, ...]
}
```
- `need_verify=true` для лет вне 2020–2027 (постановлений ещё нет / авто-правило).
- `norm` — месячные нормы часов для каждой недельной нормы (30/33/36/39/40 ч).

---

## 3. Работа с графиками (сессионные)

### `POST /api/import` — загрузка `.xls`
**Content-Type:** `multipart/form-data`  
**Поля:** `file` (`.xls`), `year` (опц.), `month` (опц.)

**Ответ:** сессия с разобранным графиком + конфликты (5 типов ошибок).

### `POST /api/schedule` — создать пустой график вручную
```json
{ "year": 2026, "month": 11 }
```
**Ответ:** сессия с пустым графиком (`manual: true`, `day_count` дней, `days_meta` для шапки).

### `GET /api/calendar/{year}` — уже описан выше.

---

## 4. CRUD сотрудников в сессии

Все эндпоинты требуют `sid` (session_id).

| Метод | Путь | Тело | Описание |
|-------|------|------|----------|
| `POST` | `/api/session/{sid}/employees` | `{name, position?, rate?, week_norm?}` | Добавить одного |
| `POST` | `/api/session/{sid}/employees/bulk` | `{employees: [{name, position?, rate?}, …]}` | Массово (исп. `embed=True`) |
| `PATCH` | `/api/session/{sid}/employees/{index}` | `{name?, position?, rate?, week_norm?}` | Изменить |
| `DELETE` | `/api/session/{sid}/employees/{index}` | — | Удалить |

**Примечания:**
- `week_norm` — 30/33/36/39/40. Если не задан, определяется по `position` через `classify()`.
- `rate` — 0.25…2.0 (шаг 0.25).
- При смене `position` без явного `week_norm` — переклассификация автоматически.

---

## 5. Редактирование ячеек и автозаполнение

| Метод | Путь | Тело | Описание |
|-------|------|------|----------|
| `POST` | `/api/session/{sid}/cell` | `{row_index, day, value}` | Записать значение в ячейку (время/код/пусто). Пересчёт валидации. |
| `POST` | `/api/session/{sid}/autofill` | `{row_index, shift, mode?}` | Заполнить пустые ячейки сменой. `mode`: `"workdays"` (только раб. дни) / `"empty"` (все пустые). |
| `POST` | `/api/session/{sid}/autocorrect` | — | Автокоррекция: норма 588н, сумма, дубликаты, сокращение предпраздничной смены. Возвращает `fixes[]`. |
| `POST` | `/api/session/{sid}/copy` | `{from_index, to_index}` | Скопировать график (врач ↔ медсестра). |

**Формат `value` для ячейки:**
- Время: `"8-15,48"`, `"12,12-20"`, `"8-12 12.30-16.30"` (разрывная)
- Коды: `"В"` (выходной), `"О"`/`"ОТ"` (отпуск), `"Б"` (больничный), `"У"`/`"ПК"` (учёба), `"Я"` (явка)
- Пусто: `""` или не передавать

---

## 6. Генерация и сохранение месяцев

| Метод | Путь | Тело | Описание |
|-------|------|------|----------|
| `POST` | `/api/session/{sid}/generate` | `{year, month, copy_shifts?}` | Новый месяц на базе текущего. `copy_shifts=true` — перенос смен по дням недели (самая частая смена для каждого дня недели). |
| `POST` | `/api/session/{sid}/save` | `{org?, dept?, title?}` | Сохранить в локальную БД (SQLite). Возвращает `id`. |
| `GET` | `/api/saved` | — | Список сохранённых месяцев + `data_dir`. |
| `POST` | `/api/saved/{id}/load` | — | Загрузить в новую сессию. |
| `POST` | `/api/saved/{id}/rename` | `{title}` | Переименовать сохранение. |
| `PATCH` | `/api/saved/{id}` | `{org?, dept?, sid}` | Обновить сохранённое из текущей сессии. |
| `DELETE` | `/api/saved/{id}` | — | Удалить сохранение. |
| `GET` | `/api/saved/export` | — | Скачать весь `med-roster.db` (файл). |
| `POST` | `/api/saved/import` | `file` (`.db`) | Импорт чужой БД (merge по содержимому, без дублей). Возвращает `added`. |

---

## 7. Экспорт отчётных форм

Все возвращают файл для скачивания (`Content-Disposition: attachment`).

| Метод | Путь | Параметры | Формат | Описание |
|-------|------|-----------|--------|----------|
| `GET` | `/api/export/csv/{sid}` | — | CSV (UTF-8) | Исправленный график для Excel/1С. |
| `GET` | `/api/export/xls/{sid}` | `org?`, `dept?` | `.xls` (xlwt) | Нативный Excel 97-2003, колонки итогов по длине месяца. Корректно импортируется обратно. |
| `GET` | `/api/export/t13/{sid}` | `org?`, `dept?` | HTML | Табель Т-13 (печатная форма). |
| `GET` | `/api/export/okud/{sid}` | `org?`, `dept?` | HTML | Табель ОКУД 0504421 (печатная форма). |
| `GET` | `/api/export/signoff/{sid}` | `org?`, `dept?` | HTML | График на подпись (Главный врач <учреждение>). |

- `org` по умолчанию — `DEFAULT_ORG` (`"ГУЗ СГП № 16"`), переопределяется в UI и хранится в `localStorage`.
- `dept` — подразделение (отделение), если задано в сессии/сохранении.

---

## 8. Центр обновлений (maintenance)

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/maintenance` | Статус: версия приложения, последние релизы GitHub/PyPI, совместимые версии зависимостей. |
| `POST` | `/api/maintenance/dependencies` | Обновить Python-зависимости через `pip install -U -r requirements.txt`. |
| `POST` | `/api/maintenance/app` | Обновить саму программу: Windows portable — скачать ZIP, распаковать, перезапуск; Linux — запустить `install.sh`; Source — только зависимости. После успеха — авто-перезапуск (`/api/shutdown`). |

---

## 9. Управление сервисом

| Метод | Путь | Описание |
|-------|------|----------|
| `POST` | `/api/shutdown` | Корректная остановка сервера (ответ уходит клиенту, затем `os._exit(0)` через 0.5 с). |
| — | `stop.bat` / `stop.sh` | Внешние скрипты: убивают процесс на порту 25625 (работают даже без `/api/shutdown`). |

---

## 10. Структура данных сессии (JSON)

Полезна для интеграций, забирающих данные напрямую из ответа `/api/import`, `/api/schedule`, `/api/session/{sid}/cell` и т.д.

```json
{
  "session_id": "abc123…",
  "source": "ноябрь 2026 общий.xls",
  "year": 2026,
  "month": 11,
  "day_count": 30,
  "manual": false,
  "department": "УПО",
  "days_meta": [
    { "day": 1, "weekday": "Вс", "off": true, "short": false },
    { "day": 2, "weekday": "Пн", "off": false, "short": false },
    { "day": 3, "weekday": "Вт", "off": false, "short": true },  // предпраздничный
    ...
  ],
  "employees": [
    {
      "index": 0,
      "name": "Иванов И.И.",
      "position": "Вр. педиатр участковый",
      "rate": 1.0,
      "week_norm": 39,
      "norm_rule": "Вр. педиатр участковый",
      "days": {
        "1": { "raw": "В", "kind": "status", "status": "day_off", "hours": 0 },
        "2": { "raw": "8-15,48", "kind": "shift", "hours": 7.8 },
        "3": { "raw": "8-14,36", "kind": "shift", "hours": 6.6 },
        ...
      },
      "total_hours": 155.0,
      "sum_col": 155.0,
      "norm_col": 155.0,
      "extra_col": "",
      "computed_norm": 155.0
    },
    ...
  ],
  "conflicts": [
    { "code": "norm_mismatch", "severity": "error", "message": "Норма в колонке Прим. 159 ≠ 155 (39 ч)", "employee": "Петров П.П.", "day": null, "details": { "expected": 155, "actual": 159 } },
    { "code": "overlap", "severity": "warning", "message": "Накладка ставок: 8-15,48 и 12,12-20 в день 5", "employee": "Сидоров С.С.", "day": 5, "details": { "shifts": ["8-15,48", "12,12-20"] } },
    ...
  ],
  "warnings": ["Строка 45: пустое ФИО, пропущена"]
}
```

### Типы конфликтов (`conflicts[].code`)

| Код | Severity | Описание |
|-----|----------|----------|
| `norm_mismatch` | error | Норма в колонке «Прим.» не совпадает с расчётной по 588н |
| `overlap` | warning | Накладка времени у сотрудника с несколькими ставками (один день — две смены) |
| `shortened_missing` | error | Нет сокращения 1 ч в предпраздничный день |
| `duplicate_row` | warning | Дубликат строки (одинаковые ФИО, должность, ставка) |
| `hours_mismatch` | error | Фактические часы ≠ колонка «Сумма» / «Прим.» |

---

## 11. Примеры интеграции

### Python: загрузка .xls, автокоррекция, экспорт CSV
```python
import requests

BASE = "http://127.0.0.1:25625"

# 1. Загрузить файл
with open("ноябрь 2026 общий.xls", "rb") as f:
    r = requests.post(f"{BASE}/api/import", files={"file": f}, data={"year": 2026, "month": 11})
session = r.json()
sid = session["session_id"]

# 2. Автокоррекция
r = requests.post(f"{BASE}/api/session/{sid}/autocorrect")
fixes = r.json()["fixes"]
print("Исправлено:", fixes)

# 3. Экспорт CSV
r = requests.get(f"{BASE}/api/export/csv/{sid}")
with open("graph_2026-11.csv", "wb") as f:
    f.write(r.content)

# 4. (опц.) Сохранить месяц в БД
requests.post(f"{BASE}/api/session/{sid}/save", json={"org": "ГУЗ СГП № 16", "dept": "УПО"})
```

### Python: чтение сохранённого месяца без UI
```python
import sqlite3, json
from pathlib import Path

# Путь к БД (Windows)
db_path = Path.home() / "AppData" / "Roaming" / "med-roster" / "med-roster.db"
# Linux: ~/.local/share/med-roster/med-roster.db

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT id, year, month, org, dept, data FROM saved_months ORDER BY year DESC, month DESC").fetchall()

for r in rows:
    data = json.loads(r["data"])
    print(f"{r['year']}-{r['month']:02d} {r['org']} {r['dept']}: {len(data['employees'])} чел.")
    # data['employees'] — список с полями name, position, rate, week_norm, days{...}
```

### 1С / внешняя система: получить календарь и нормы на год
```http
GET http://127.0.0.1:25625/api/calendar/2026
```
Используйте `months[].norm` для расчёта норм в своей системе.

---

## 12. Ограничения и нюансы для интеграторов

1. **In-memory сессии** — при перезапуске сервера все `sid` теряются. Для долгого хранения используйте `/api/session/{sid}/save` → `/api/saved/{id}/load`.
2. **Макс. 8 сессий** — при превышении удаляется самая старая. Не держите долго открытые сессии в скриптах.
3. **Порт 25625** — жёстко задан. Если занят, сервис не запустится (см. `run.py` + `stop.bat`/`stop.sh`).
4. **Кодировка** — везде UTF-8. В `.xls` (xlrd/xlwt) кодировка cp1251 внутри, конвертация автоматическая.
5. **Windows 7** — целевая платформа. API работает на Python 3.8+; если вызываете из современного Python — совместимости нет проблем.
6. **Без авторизации** — если вешаете на сеть, добавьте reverse proxy (nginx + basic auth / mTLS / VPN).

---

## 13. Полезные ссылки в коде

| Файл | Назначение |
|------|------------|
| `app/main.py` | Все эндпоинты (FastAPI) |
| `app/services/xls_importer.py` | Парсер `.xls`, сериализация |
| `app/services/exporter.py` | CSV, XLS, HTML-формы (Т-13, ОКУД, подпись) |
| `app/services/conflict_checker.py` | 5 типов валидации |
| `app/services/autocorrect.py` | Автоисправление типичных ошибок |
| `app/services/scheduler.py` | Автозаполнение, копирование, генерация месяца |
| `app/core/storage.py` | SQLite: сохранение/загрузка/экспорт БД |
| `app/core/calendar_rf.py` | Производственный календарь РФ (любой год) |
| `app/services/updater.py` | Центр обновлений (GitHub + PyPI) |

---

## 14. Чего НЕТ в API (пока)

- Webhook'ов / Server-Sent Events — опросите `/api/health` или `/api/saved` по таймеру.
- GraphQL — только REST + JSON.
- Мультитенантность / разделение прав — однопользовательское локальное приложение.
- Прямой доступ к БД извне — используйте `/api/saved/export` (скачать `.db`) или читайте файл напрямую (путь в `/api/saved` → `data_dir`).

---

*Документ актуален для релиза **0.6.4**. При обновлении версии проверяйте `CHANGELOG.md` и `app/main.py`.*