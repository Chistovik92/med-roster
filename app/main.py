# -*- coding: utf-8 -*-
"""
Веб-интерфейс «МедГрафик: Поликлиника» (FastAPI + vanilla JS).

Эндпоинты:
  * GET  /                    — одностраничный интерфейс (index.html);
  * GET  /api/health          — статус;
  * GET  /api/calendar/{year} — производственный календарь и нормы на год;
  * POST /api/import          — загрузка .xls → разбор + валидация (5 типов).

Запуск: ``uvicorn app.main:app`` или через start.bat / start.sh.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, UploadFile, Body
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.core.calendar_rf import get_year_calendar
from app.core.constants import VALID_WEEK_NORMS
from app.services.conflict_checker import check_all, Conflict
from app.services.exporter import export_csv, export_t13_html, export_okud_html, export_signoff_html
from app.services.scheduler import autofill, copy_schedule
from app.services.time_parser import parse_cell
from app.services.xls_importer import import_xls, ImportResult, EmployeeRow

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = FastAPI(title="МедГрафик: Поликлиника", version="0.1.0")

# In-memory хранилище сессий импорта: session_id -> (ImportResult, conflicts).
# Хранит только разобранные данные в памяти процесса (не персональные файлы).
_sessions: Dict[str, Dict[str, Any]] = {}


# --------------------------------------------------------------------------- #
#  Сериализация в JSON
# --------------------------------------------------------------------------- #
def _row_to_dict(row: EmployeeRow, day_count: int) -> Dict[str, Any]:
    days: Dict[str, Dict[str, Any]] = {}
    for d in range(1, day_count + 1):
        raw = row.raw_cells.get(d, "")
        pc = row.parsed.get(d)
        if pc is None:
            days[str(d)] = {"raw": raw, "kind": "empty", "hours": 0.0}
        elif pc.kind == "status":
            days[str(d)] = {"raw": raw, "kind": "status", "status": pc.status, "hours": 0.0}
        elif pc.kind == "shift":
            days[str(d)] = {"raw": raw, "kind": "shift", "hours": pc.total_hours}
        else:
            days[str(d)] = {"raw": raw, "kind": "invalid", "error": pc.error, "hours": 0.0}
    return {
        "index": row.index,
        "name": row.name,
        "position": row.position,
        "rate": row.rate,
        "week_norm": row.week_norm,
        "norm_rule": row.norm_rule,
        "days": days,
        "total_hours": round(row.total_hours, 2),
        "sum_col": row.sum_col,
        "norm_col": row.norm_col,
        "extra_col": row.extra_col,
    }


def _conflict_to_dict(c: Conflict) -> Dict[str, Any]:
    return {
        "code": c.code,
        "severity": c.severity,
        "message": c.message,
        "employee": c.employee,
        "day": c.day,
        "details": c.details,
    }


def _result_to_dict(res: ImportResult, conflicts: List[Conflict]) -> Dict[str, Any]:
    return {
        "source": os.path.basename(res.source),
        "year": res.year,
        "month": res.month,
        "day_count": res.day_count,
        "employees": [_row_to_dict(r, res.day_count) for r in res.rows],
        "conflicts": [_conflict_to_dict(c) for c in conflicts],
        "warnings": res.warnings,
    }


# --------------------------------------------------------------------------- #
#  Роуты
# --------------------------------------------------------------------------- #
@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "app": "med-roster", "version": "0.1.0"}


@app.get("/api/calendar/{year}")
def calendar(year: int) -> Dict[str, Any]:
    cal = get_year_calendar(year)
    months = []
    for m in range(1, 13):
        work, short = cal.month_stats(m)
        norms = {str(w): cal.norm_hours(w, month=m) for w in VALID_WEEK_NORMS}
        months.append({"month": m, "work": work, "short": short, "norm": norms})
    short_days = [{"month": d.date.month, "day": d.date.day}
                  for d in cal.days if d.is_shortened]
    holidays = [{"month": d.date.month, "day": d.date.day}
                for d in cal.days if d.is_holiday]
    return {
        "year": year,
        "need_verify": cal.need_verify,
        "months": months,
        "year_norm": {str(w): cal.norm_hours(w) for w in VALID_WEEK_NORMS},
        "short_days": short_days,
        "holidays": holidays,
    }


@app.post("/api/import")
async def import_file(file: UploadFile = File(...),
                      year: Optional[int] = Form(None),
                      month: Optional[int] = Form(None)) -> JSONResponse:
    """Загрузить .xls, разобрать и провалидировать."""
    data = await file.read()
    if not data:
        return JSONResponse(status_code=400, content={"error": "пустой файл"})

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xls")
    try:
        tmp.write(data)
        tmp.close()
        res = import_xls(tmp.name, year=year, month=month)
        conflicts = check_all(res)
        sid = uuid.uuid4().hex
        _sessions[sid] = {"result": res, "conflicts": conflicts}
        payload = _result_to_dict(res, conflicts)
        payload["session_id"] = sid
        return JSONResponse(content=payload)
    except Exception as exc:  # noqa: BLE001 — отдаём понятную ошибку клиенту
        return JSONResponse(status_code=422, content={"error": str(exc)})
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


@app.post("/api/session/{sid}/cell")
def edit_cell(sid: str,
              row_index: int = Body(...),
              day: int = Body(...),
              value: str = Body("")) -> JSONResponse:
    """Изменить одну ячейку графика и пересчитать валидацию.

    ``row_index`` — исходный номер строки сотрудника (поле ``index`` из импорта),
    ``day`` — день месяца (1-based), ``value`` — новое значение ячейки
    (интервал времени, код статуса или пустая строка).
    """
    session = _sessions.get(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]

    row = None
    for r in res.rows:
        if r.index == row_index:
            row = r
            break
    if row is None:
        return JSONResponse(status_code=404, content={"error": "сотрудник не найден"})
    if not (1 <= day <= res.day_count):
        return JSONResponse(status_code=422, content={"error": "неверный день"})

    value = (value or "").strip()
    row.raw_cells[day] = value
    if value == "":
        row.parsed.pop(day, None)
    else:
        row.parsed[day] = parse_cell(value)
    row.total_hours = sum(p.total_hours for p in row.parsed.values())

    conflicts = check_all(res)
    session["conflicts"] = conflicts
    payload = _result_to_dict(res, conflicts)
    payload["session_id"] = sid
    return JSONResponse(content=payload)


@app.post("/api/session/{sid}/autofill")
def autofill_route(sid: str,
                   row_index: int = Body(...),
                   shift: str = Body(...),
                   mode: str = Body("workdays")) -> JSONResponse:
    """Заполнить пустые ячейки сотрудника заданной сменой.

    ``mode`` — ``"workdays"`` (только рабочие дни) или ``"empty"`` (все пустые).
    """
    session = _sessions.get(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    try:
        warnings = autofill(res, row_index, shift, mode)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})
    conflicts = check_all(res)
    session["conflicts"] = conflicts
    payload = _result_to_dict(res, conflicts)
    payload["session_id"] = sid
    payload["warnings"] = res.warnings + warnings
    return JSONResponse(content=payload)


@app.post("/api/session/{sid}/copy")
def copy_route(sid: str,
               from_index: int = Body(...),
               to_index: int = Body(...)) -> JSONResponse:
    """Скопировать график одного сотрудника другому (синхронизация врач↔медсестра)."""
    session = _sessions.get(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    try:
        copy_schedule(res, from_index, to_index)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})
    conflicts = check_all(res)
    session["conflicts"] = conflicts
    payload = _result_to_dict(res, conflicts)
    payload["session_id"] = sid
    return JSONResponse(content=payload)


@app.get("/api/export/csv/{sid}")
def export_csv_route(sid: str) -> Response:
    """Выгрузить исправленный график в CSV."""
    session = _sessions.get(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    csv_text = export_csv(res)
    filename = "graph_%d-%02d.csv" % (res.year, res.month)
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 'attachment; filename="%s"' % filename},
    )


@app.get("/api/export/t13/{sid}")
def export_t13_route(sid: str, org: Optional[str] = None,
                     dept: Optional[str] = None) -> Response:
    """Сформировать табель Т-13 (печатный HTML)."""
    session = _sessions.get(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    html_text = export_t13_html(res, org=org or "ГУЗ «СГП № 16»",
                                dept=dept or "")
    filename = "tabel_T13_%d-%02d.html" % (res.year, res.month)
    return Response(
        content=html_text,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition":
                 'attachment; filename="%s"' % filename},
    )


@app.get("/api/export/okud/{sid}")
def export_okud_route(sid: str, org: Optional[str] = None,
                      dept: Optional[str] = None) -> Response:
    """Сформировать табель ОКУД 0504421 (печатный HTML)."""
    session = _sessions.get(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    html_text = export_okud_html(res, org=org or "ГУЗ «СГП № 16»",
                                 dept=dept or "")
    filename = "tabel_OKUD0504421_%d-%02d.html" % (res.year, res.month)
    return Response(
        content=html_text,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition":
                 'attachment; filename="%s"' % filename},
    )


@app.get("/api/export/signoff/{sid}")
def export_signoff_route(sid: str, org: Optional[str] = None,
                         dept: Optional[str] = None) -> Response:
    """Сформировать график на подпись (печатный HTML)."""
    session = _sessions.get(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    html_text = export_signoff_html(res, org=org or "ГУЗ «СГП № 16»",
                                    dept=dept or "")
    filename = "graph_podpis_%d-%02d.html" % (res.year, res.month)
    return Response(
        content=html_text,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition":
                 'attachment; filename="%s"' % filename},
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
