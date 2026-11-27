# -*- coding: utf-8 -*-
"""
Веб-интерфейс «МедГрафик: Поликлиника» (FastAPI + vanilla JS).

Эндпоинты:
  * GET  /                    — одностраничный интерфейс (index.html);
  * GET  /api/health          — статус;
  * GET  /api/calendar/{year} — производственный календарь и нормы на год;
  * POST /api/import          — загрузка .xls → разбор + валидация (5 типов).

Интеграционный слой (с 0.10.0):
  * те же роуты доступны с префиксом ``/api/v1`` (контракт для МИС;
    OpenAPI-схема — ``/api/openapi.json``, Swagger UI — ``/api/docs``);
  * авторизация внешних запросов по API-ключу (``X-API-Key``), см.
    ``app/core/api_auth.py``;
  * ограничение частоты запросов (``app/core/rate_limiter.py``);
  * аудит всех запросов к API (``app/core/audit.py``);
  * CORS (``MEDROSTER_CORS_ORIGINS``), см. ``app/core/config.py``.

Локальные запросы (UI с того же компьютера) работают без ключа и лимитов,
как и раньше: обратная совместимость гарантирована.

Запуск: ``uvicorn app.main:app`` или через start.bat / start.sh.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, File, Form, UploadFile, Body, APIRouter, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app import __version__
from app.core import storage, config, signing
from app.core import api_auth
from app.services import webhooks
from app.core.audit import AuditLog
from app.core.rate_limiter import RateLimiter
from app.core.calendar_rf import get_year_calendar, WEEKDAY_RU
from app.core.constants import VALID_WEEK_NORMS, DEFAULT_ORG
from app.services.autocorrect import autocorrect
from app.services.conflict_checker import check_all, Conflict
from app.services.exporter import (export_csv, export_xls, export_t13_html,
                                    export_okud_html, export_signoff_html,
                                    export_signed_zip, verify_signed_zip)
from app.services.fhir_exporter import export_fhir_bundle
from app.services.norm_calculator import monthly_base_norm
from app.services.position_classifier import classify
from app.services.scheduler import autofill, copy_schedule, generate_month
from app.services.time_parser import parse_cell
from app.services import updater
from app.services.xls_importer import (
    import_xls, ImportResult, EmployeeRow,
    create_manual_schedule, serialize_result, deserialize_result,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Один роутер подключается дважды:
#   * с префиксом /api/v1 — контракт для МИС (попадает в OpenAPI-схему);
#   * с префиксом /api    — прежние пути для UI и обратной совместимости
#     (include_in_schema=False, чтобы схема описывала только /api/v1).
router = APIRouter()

app = FastAPI(
    title="МедГрафик: Поликлиника",
    version=__version__,
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# In-memory хранилище сессий импорта: session_id -> dict(result, conflicts, at).
# Хранит только разобранные данные в памяти процесса (не персональные файлы).
_sessions: Dict[str, Dict[str, Any]] = {}

# Ограничение на число одновременно хранимых сессий (защита от роста памяти).
# Для локального одно-пользовательского приложения достаточно 8; при превышении
# самая старая сессия вытесняется (порядок вставки в dict сохраняется, Py 3.7+).
_MAX_SESSIONS = 8
# Время жизни сессии без обращений, секунды (30 минут).
_SESSION_TTL = 30 * 60

# Максимальный размер загружаемого файла (байты). График поликлиники (~124 чел.)
# в формате .xls весит десятки КБ; лимит защищает от случайной загрузки гиганта
# и от исчерпания памяти на слабом железе (2 ГБ).
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 МБ


# --------------------------------------------------------------------------- #
#  Интеграционный слой: аудит, авторизация, rate limit, CORS
# --------------------------------------------------------------------------- #
audit_log = AuditLog(flush_interval=2.0, batch=50)
rate_limiter = RateLimiter()
audit_log.set_rate_limiter(rate_limiter)

_LOCAL_IPS = {"127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"}

# Эндпоинты, доступные только локальному администратору (или по X-Admin-Token):
# остановка сервера, обновление приложения/зависимостей, управление ключами
# и чтение/очистка аудита. Проверяется по нормализованному пути без префикса.
_LOCAL_ONLY_PATHS = ("/shutdown",)
_LOCAL_ONLY_PREFIXES = ("/keys", "/audit", "/maintenance/app",
                        "/maintenance/dependencies")


def _client_ip(request: Request) -> str:
    """IP клиента (с учётом reverse proxy, если включён MEDROSTER_TRUST_PROXY)."""
    if config.TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    client = request.client
    return (client.host if client else "") or ""


def _is_local(ip: str) -> bool:
    return ip in _LOCAL_IPS


def _normalized_api_path(path: str) -> str:
    """Путь без префикса /api или /api/v1 (для проверки локальных эндпоинтов)."""
    if path.startswith("/api/v1"):
        return path[len("/api/v1"):]
    if path.startswith("/api"):
        return path[len("/api"):]
    return path


def _is_local_only(path: str) -> bool:
    p = _normalized_api_path(path)
    if p in _LOCAL_ONLY_PATHS:
        return True
    for prefix in _LOCAL_ONLY_PREFIXES:
        if p == prefix or p.startswith(prefix + "/"):
            return True
    return False


def _admin_token_ok(request: Request) -> bool:
    """Совпал ли заголовок X-Admin-Token с MEDROSTER_ADMIN_TOKEN."""
    token = config.ADMIN_TOKEN
    return bool(token) and request.headers.get("x-admin-token", "") == token


def _is_admin_request(request: Request, local: bool) -> bool:
    """Локальный клиент ИЛИ совпавший X-Admin-Token (MEDROSTER_ADMIN_TOKEN)."""
    if local:
        return True
    return _admin_token_ok(request)


def _is_heavy(path: str, method: str) -> bool:
    """«Тяжёлые» запросы: импорт .xls/.db и все экспорты (отдельный лимит)."""
    p = path.lower()
    if "/export/" in p:
        return True
    if method == "POST" and p.endswith("/import"):
        return True
    return False


class AuditMiddleware(BaseHTTPMiddleware):
    """Аудит всех запросов к /api/*: время, метод, путь, статус, IP, ключ, результат.

    Работает снаружи авторизации, чтобы в журнал попадали и отклонённые
    запросы (401 неверный ключ, 429 превышен лимит, 403 доступ запрещён).
    """

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        try:
            response = await call_next(request)
        except Exception:
            if request.url.path.startswith("/api"):
                info = request.scope.get("mrauth", {})
                audit_log.log({
                    "ts": time.time(),
                    "method": request.method,
                    "path": request.url.path,
                    "status": 500,
                    "client_ip": _client_ip(request),
                    "api_key_id": info.get("api_key_id"),
                    "tenant": info.get("tenant"),
                    "auth_status": info.get("status", "anonymous"),
                    "duration_ms": round((time.time() - start) * 1000.0, 1),
                })
            raise
        if request.url.path.startswith("/api"):
            info = request.scope.get("mrauth", {})
            audit_log.log({
                "ts": time.time(),
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "client_ip": _client_ip(request),
                "api_key_id": info.get("api_key_id"),
                "tenant": info.get("tenant"),
                "auth_status": info.get("status", "anonymous"),
                "duration_ms": round((time.time() - start) * 1000.0, 1),
            })
        return response


class AuthMiddleware(BaseHTTPMiddleware):
    """Авторизация: X-API-Key для внешних клиентов; локальный UI — без ключа.

    Результат кладётся в ``scope["mrauth"]`` (доступен аудиту и rate limit):
      * authorized         — валидный ключ (api_key_id, tenant заполнены);
      * authorized_admin   — удалённый запрос с верным X-Admin-Token;
      * anonymous_local    — локальный запрос без ключа (UI, как раньше);
      * anonymous          — запрос без ключа при «открытом» режиме (ключей нет);
      * rejected_bad_key   — неверный/отозванный ключ → 401;
      * rejected_no_key    — внешний запрос без ключа при наличии ключей → 401;
      * forbidden_remote   — локальный эндпоинт с внешнего клиента → 403;
      * rate_limited       — 429 от RateLimitMiddleware.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # scope общий для всей цепочки middleware: наружные слои прочитают
        # результат авторизации после обработки запроса.
        info: Dict[str, Any] = {"status": "anonymous_local"}
        request.scope["mrauth"] = info

        if not path.startswith("/api"):
            return await call_next(request)
        if request.method == "OPTIONS":
            # CORS-preflight обрабатывает CORSMiddleware снаружи; OPTIONS
            # сюда попасть не должен, но авторизацию на всякий случай не
            # проверяем.
            info["status"] = "options"
            return await call_next(request)

        ip = _client_ip(request)
        local = _is_local(ip)
        key = request.headers.get("x-api-key", "").strip()

        if key:
            key_info = api_auth.verify_key(key)
            if key_info is None:
                info["status"] = "rejected_bad_key"
                return JSONResponse(
                    status_code=401,
                    content={"error": "неверный или отозванный API-ключ"})
            info.update({
                "status": "authorized",
                "api_key_id": key_info["id"],
                "tenant": key_info["tenant"],
                "label": key_info["label"],
            })
        elif local:
            # UI с того же компьютера — работает без ключа (обратная совместимость)
            info["status"] = "anonymous_local"
        elif _admin_token_ok(request):
            # удалённый администратор с корректным X-Admin-Token
            info["status"] = "authorized_admin"
        elif config.REQUIRE_API_KEY or api_auth.has_active_keys():
            # ключи настроены → внешние анонимные запросы запрещены
            info["status"] = "rejected_no_key"
            return JSONResponse(
                status_code=401,
                content={"error": "требуется API-ключ (заголовок X-API-Key)"})
        else:
            # ключей нет и REQUIRE_API_KEY не задан → прежний открытый режим
            info["status"] = "anonymous"

        # Локально-ограниченные эндпоинты: только администратор машины
        if _is_local_only(path) and not _is_admin_request(request, local):
            info["status"] = "forbidden_remote"
            return JSONResponse(
                status_code=403,
                content={"error": "доступ только с локального компьютера"})

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Ограничение частоты для внешних запросов (по ключу либо по IP).

    Локальный UI лимитами не ограничивается. «Тяжёлые» эндпоинты (импорт,
    экспорт) имеют отдельный, более строгий лимит. Значения читаются из
    ``app.core.config`` в момент запроса.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api") or request.method == "OPTIONS":
            return await call_next(request)
        info = request.scope.get("mrauth", {})
        if info.get("status") == "anonymous_local":
            return await call_next(request)

        if info.get("api_key_id") is not None:
            subject = "key:%d" % info["api_key_id"]
        else:
            subject = "ip:%s" % _client_ip(request)

        # Heavy and normal requests are counted SEPARATELY: they have
        # different limits, so the buckets must be independent.
        if _is_heavy(path, request.method):
            limit = config.HEAVY_RATE_LIMIT_PER_MIN
            subject = subject + ":heavy"
        else:
            limit = config.RATE_LIMIT_PER_MIN
        window = config.RATE_LIMIT_WINDOW

        if not rate_limiter.check(subject, limit, window):
            info["status"] = "rate_limited"
            retry_after = int(rate_limiter.retry_after(subject, window)) or 1
            return JSONResponse(
                status_code=429,
                content={"error": "превышен лимит запросов (%d за %d сек)" % (limit, window)},
                headers={"Retry-After": str(retry_after)})
        return await call_next(request)


# Порядок add_middleware: ПОСЛЕДНИЙ добавленный работает ПЕРВЫМ на запросе.
# Цепочка на запрос: CORS → Аудит → Авторизация → RateLimit → роуты.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(AuditMiddleware)
_origins = config.CORS_ORIGINS if config.CORS_ORIGINS else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)


def _gc_sessions() -> None:
    """Вытеснить просроченные и лишние сессии (защита от роста памяти)."""
    now = time.time()
    # удаляем сессии с истёкшим TTL
    for sid in [s for s, v in _sessions.items() if now - v.get("at", now) > _SESSION_TTL]:
        _sessions.pop(sid, None)
    # вытесняем самые старые при превышении лимита
    while len(_sessions) > _MAX_SESSIONS:
        oldest = next(iter(_sessions))
        _sessions.pop(oldest, None)


def _get_session(sid: str) -> Optional[Dict[str, Any]]:
    """Достать сессию и обновить время последнего обращения."""
    _gc_sessions()
    session = _sessions.get(sid)
    if session is not None:
        session["at"] = time.time()
    return session


# --------------------------------------------------------------------------- #
#  Сериализация в JSON
# --------------------------------------------------------------------------- #
def _row_to_dict(row: EmployeeRow, result: ImportResult) -> Dict[str, Any]:
    day_count = result.day_count
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
    # Расчётная месячная норма по 588н (для ручных строк, где нет колонки «Прим.»).
    computed_norm = None
    if row.week_norm is not None:
        computed_norm = round(
            monthly_base_norm(row.week_norm, result.year, result.month, row.rate), 1)
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
        "computed_norm": computed_norm,
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


def _days_meta(res: ImportResult) -> List[Dict[str, Any]]:
    """Метаданные дней месяца для шапки таблицы: день недели, выходной/сокращённый.

    Нужны фронтенду, чтобы подсвечивать выходные/праздники и предпраздничные дни
    и подписывать колонки «Пн 1», «Вт 2»… при вводе графика.
    """
    cal = get_year_calendar(res.year)
    meta: List[Dict[str, Any]] = []
    for d in range(1, res.day_count + 1):
        info = cal.day(res.month, d)
        if info is None:
            meta.append({"day": d, "weekday": "", "off": False, "short": False})
        else:
            meta.append({"day": d, "weekday": WEEKDAY_RU[info.weekday],
                         "off": (not info.is_work), "short": info.is_shortened})
    return meta


def _result_to_dict(res: ImportResult, conflicts: List[Conflict]) -> Dict[str, Any]:
    return {
        "source": os.path.basename(res.source),
        "year": res.year,
        "month": res.month,
        "day_count": res.day_count,
        "manual": res.manual,
        "department": res.department,
        "days_meta": _days_meta(res),
        "employees": [_row_to_dict(r, res) for r in res.rows],
        "conflicts": [_conflict_to_dict(c) for c in conflicts],
        "warnings": res.warnings,
    }


def _new_session_payload(res: ImportResult) -> Tuple[str, Dict[str, Any]]:
    """Создать сессию для готового графика; вернуть (session_id, payload)."""
    conflicts = check_all(res)
    sid = uuid.uuid4().hex
    _sessions[sid] = {"result": res, "conflicts": conflicts, "at": time.time()}
    _gc_sessions()
    payload = _result_to_dict(res, conflicts)
    payload["session_id"] = sid
    return sid, payload


def _new_session(res: ImportResult) -> JSONResponse:
    """Создать сессию для готового графика и вернуть его сериализацию."""
    _sid, payload = _new_session_payload(res)
    return JSONResponse(content=payload)


def _refresh_session(sid: str,
                     extra: Optional[Dict[str, Any]] = None) -> JSONResponse:
    """Пересчитать валидацию текущей сессии и вернуть её сериализацию.

    ``extra`` — дополнительные поля ответа (например, отчёт синхронизации).
    """
    session = _sessions.get(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    conflicts = check_all(res)
    session["conflicts"] = conflicts
    _autosave_draft(res)
    payload = _result_to_dict(res, conflicts)
    payload["session_id"] = sid
    if extra:
        payload.update(extra)
    return JSONResponse(content=payload)


def _find_row(res: ImportResult, row_index: int) -> Optional[EmployeeRow]:
    for r in res.rows:
        if r.index == row_index:
            return r
    return None


def _autosave_draft(res: ImportResult) -> None:
    """Сохранить текущий график как черновик (страховка от потери работы).

    Пишет через ``storage.save_draft`` (атомарно). Ошибки записи не должны
    ломать основной поток редактирования — поэтому молча игнорируем их (черновик
    — это только подстраховка, основное сохранение пользователь делает сам).
    """
    try:
        storage.save_draft(serialize_result(res))
    except OSError:
        pass


def _emit_schedule_changed(res: ImportResult, sid: str, action: str) -> None:
    """Уведомить МИС (вебхуки) об изменении графика в сессии.

    Ошибки доставки не должны влиять на работу интерфейса — вебхуки
    асинхронны, поэтому любые сбои молча игнорируются (счётчики неудач
    в БД покажут проблему администратору).
    """
    try:
        webhooks.emit_event("schedule.changed", {
            "subject": sid,
            "session_id": sid,
            "year": res.year,
            "month": res.month,
            "action": action,
        })
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
#  Роуты (один и тот же роутер доступен как /api/... для UI, так и /api/v1/...
#  для МИС; см. include_router в конце файла)
# --------------------------------------------------------------------------- #
@router.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "app": "med-roster", "version": __version__}


# --------------------------------------------------------------------------- #
#  Остановка сервиса (только локально / X-Admin-Token)
# --------------------------------------------------------------------------- #
# Пауза перед завершением процесса — чтобы ответ клиенту успел уйти по сети.
SHUTDOWN_DELAY = 0.5


def _stop_process() -> None:
    """Немедленно завершить процесс (не вызывать напрямую в тестах)."""
    os._exit(0)


def _schedule_shutdown() -> None:
    """Запланировать остановку сервера через короткую паузу.

    Остановка выполняется в фоновом потоке: обработчик успевает вернуть ответ
    клиенту, после чего процесс завершается принудительно (``os._exit``). Это
    надёжно работает во всех режимах запуска — ``run.py`` (в т.ч. PyInstaller
    GUI-сборка) и ``python -m uvicorn app.main:app`` из start.bat / start.sh.
    """
    def _stop() -> None:
        time.sleep(SHUTDOWN_DELAY)
        _stop_process()

    threading.Thread(target=_stop, daemon=True).start()


@router.post("/shutdown")
def shutdown() -> JSONResponse:
    """Остановить сервис (завершить процесс сервера)."""
    _schedule_shutdown()
    return JSONResponse(content={"status": "stopping",
                                 "message": "Сервис останавливается…"})


@router.get("/calendar/{year}")
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


@router.post("/import")
async def import_file(file: UploadFile = File(...),
                      year: Optional[int] = Form(None),
                      month: Optional[int] = Form(None)) -> JSONResponse:
    """Загрузить .xls, разобрать и провалидировать."""
    data = await file.read()
    if not data:
        return JSONResponse(status_code=400, content={"error": "пустой файл"})
    if len(data) > MAX_UPLOAD_BYTES:
        return JSONResponse(status_code=413, content={
            "error": "файл слишком большой (максимум 20 МБ)"})

    try:
        res = import_xls(data, year=year, month=month, filename=file.filename)
        conflicts = check_all(res)
        sid = uuid.uuid4().hex
        _sessions[sid] = {"result": res, "conflicts": conflicts, "at": time.time()}
        _gc_sessions()
        payload = _result_to_dict(res, conflicts)
        payload["session_id"] = sid
        return JSONResponse(content=payload)
    except Exception as exc:  # noqa: BLE001 — отдаём понятную ошибку клиенту
        return JSONResponse(status_code=422, content={"error": str(exc)})


# --------------------------------------------------------------------------- #
#  Ручной ввод графика
# --------------------------------------------------------------------------- #
@router.post("/schedule")
def create_schedule(year: int = Body(...), month: int = Body(...)) -> JSONResponse:
    """Создать пустой график для ручного ввода (год + месяц)."""
    try:
        res = create_manual_schedule(year, month)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})
    return _new_session(res)


# --------------------------------------------------------------------------- #
#  Сотрудники (CRUD)
# --------------------------------------------------------------------------- #
@router.post("/session/{sid}/employees")
def add_employee(sid: str,
                 name: str = Body(...),
                 position: str = Body(""),
                 rate: float = Body(1.0),
                 week_norm: Optional[int] = Body(None)) -> JSONResponse:
    """Добавить сотрудника в график (ручной ввод)."""
    session = _get_session(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]

    name = (name or "").strip()
    if not name:
        return JSONResponse(status_code=422, content={"error": "укажите Ф.И.О."})
    position = (position or "").strip()
    if rate is None or rate <= 0 or rate > 2:
        return JSONResponse(status_code=422, content={"error": "неверная ставка"})

    # недельную норму определяем по должности, если не задана явно
    if week_norm is None and position:
        week_norm, _r = classify(position)

    idx = max([r.index for r in res.rows], default=-1) + 1
    res.rows.append(EmployeeRow(index=idx, name=name, position=position,
                                rate=float(rate), week_norm=week_norm))
    _emit_schedule_changed(res, sid, "employee.add")
    return _refresh_session(sid)


@router.post("/session/{sid}/employees/bulk")
def add_employees_bulk(sid: str,
                       employees: List[Dict[str, Any]] = Body(..., embed=True)) -> JSONResponse:
    """Массовое добавление сотрудников (список {name, position, rate}).

    Используется кнопкой «Добавить списком»: вставляется многострочный текст
    «ФИО; должность; ставка» и все строки добавляются одним запросом.
    """
    session = _get_session(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]

    added = 0
    for e in employees:
        name = (e.get("name") or "").strip()
        if not name:
            continue
        position = (e.get("position") or "").strip()
        try:
            rate = float(e.get("rate", 1.0) or 1.0)
        except (TypeError, ValueError):
            rate = 1.0
        if rate <= 0 or rate > 2:
            rate = 1.0
        week_norm = None
        if position:
            week_norm, _r = classify(position)
        idx = max([r.index for r in res.rows], default=-1) + 1
        res.rows.append(EmployeeRow(index=idx, name=name, position=position,
                                    rate=float(rate), week_norm=week_norm))
        added += 1
    if added == 0:
        return JSONResponse(status_code=422,
                            content={"error": "нет корректных строк (нужно Ф.И.О.)"})
    _emit_schedule_changed(res, sid, "employee.bulk")
    return _refresh_session(sid)


@router.patch("/session/{sid}/employees/{index}")
def update_employee(sid: str, index: int,
                    name: Optional[str] = Body(None),
                    position: Optional[str] = Body(None),
                    rate: Optional[float] = Body(None),
                    week_norm: Optional[int] = Body(None)) -> JSONResponse:
    """Изменить сотрудника: ФИО, должность, ставку и/или недельную норму."""
    session = _get_session(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    row = _find_row(res, index)
    if row is None:
        return JSONResponse(status_code=404, content={"error": "сотрудник не найден"})

    if name is not None:
        name = name.strip()
        if not name:
            return JSONResponse(status_code=422, content={"error": "Ф.И.О. не может быть пустым"})
        row.name = name
    if position is not None:
        position = position.strip()
        row.position = position
        if week_norm is None:
            # должность изменилась и норма не задана явно — переклассифицируем
            row.week_norm, _r = classify(position)
            row.norm_rule = None
    if rate is not None:
        if rate <= 0 or rate > 2:
            return JSONResponse(status_code=422, content={"error": "неверная ставка"})
        row.rate = float(rate)
    if week_norm is not None:
        row.week_norm = week_norm
    _emit_schedule_changed(res, sid, "employee.update")
    return _refresh_session(sid)


@router.delete("/session/{sid}/employees/{index}")
def delete_employee(sid: str, index: int) -> JSONResponse:
    """Удалить сотрудника из графика."""
    session = _get_session(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    row = _find_row(res, index)
    if row is None:
        return JSONResponse(status_code=404, content={"error": "сотрудник не найден"})
    res.rows.remove(row)
    _emit_schedule_changed(res, sid, "employee.delete")
    return _refresh_session(sid)


# --------------------------------------------------------------------------- #
#  Сохранение / загрузка / генерация следующих месяцев
# --------------------------------------------------------------------------- #
@router.post("/session/{sid}/save")
def save_schedule(sid: str, org: str = Body("", embed=True),
                  dept: str = Body("", embed=True),
                  title: str = Body("", embed=True)) -> JSONResponse:
    """Сохранить текущий график в локальное хранилище (новая копия)."""
    session = _get_session(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    res.department = (dept or "").strip()
    try:
        saved_id = storage.save_month(res.year, res.month, org or DEFAULT_ORG,
                                      serialize_result(res), title=(title or ""))
        storage.clear_draft()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(exc)})
    try:
        webhooks.emit_event("month.saved", {
            "subject": str(saved_id), "saved_id": saved_id,
            "year": res.year, "month": res.month,
            "org": org or DEFAULT_ORG, "department": res.department,
            "employee_count": len(res.rows),
            "title": (title or "").strip(),
        })
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse(content={"id": saved_id, "year": res.year,
                                 "month": res.month})


@router.get("/saved")
def saved_list() -> JSONResponse:
    """Список сохранённых месяцев."""
    try:
        return JSONResponse(content={"saved": storage.list_saved(),
                                     "data_dir": storage.get_data_dir()})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(exc)})


# --------------------------------------------------------------------------- #
#  Черновик: автосохранение текущей работы и восстановление после перезапуска
# --------------------------------------------------------------------------- #
@router.get("/draft")
def draft_info() -> JSONResponse:
    """Сводка о сохранённом черновике (есть ли, период, число сотрудников)."""
    try:
        return JSONResponse(content=storage.draft_info())
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.post("/draft/restore")
def draft_restore() -> JSONResponse:
    """Восстановить черновик в новую сессию (если он есть).

    Возвращает 404, если черновика нет. Используется при старте, чтобы вернуть
    пользователю несохранённую работу после перезапуска программы.
    """
    data = storage.load_draft()
    if data is None:
        return JSONResponse(status_code=404, content={"error": "черновика нет"})
    try:
        res = deserialize_result(data)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=422, content={"error": str(exc)})
    return _new_session(res)


@router.delete("/draft")
def draft_clear() -> JSONResponse:
    """Удалить черновик (пользователь решил начать заново / сохранил месяц)."""
    storage.clear_draft()
    return JSONResponse(content={"cleared": True})


@router.post("/saved/{saved_id}/rename")
def rename_saved_route(saved_id: int, title: str = Body(..., embed=True)) -> JSONResponse:
    """Переименовать сохранённый месяц."""
    ok = storage.rename_saved(saved_id, title)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "сохранение не найдено"})
    return JSONResponse(content={"id": saved_id, "title": (title or "").strip()})


@router.patch("/saved/{saved_id}")
def update_saved_route(saved_id: int, org: str = Body(""), dept: str = Body(""),
                       sid: str = Body(...)) -> JSONResponse:
    """Обновить данные сохранённого месяца из текущей сессии."""
    session = _get_session(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    res.department = (dept or "").strip()
    payload = serialize_result(res)
    ok = storage.update_saved(saved_id, org or DEFAULT_ORG, (dept or "").strip(), payload)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "сохранение не найдено"})
    try:
        webhooks.emit_event("month.updated", {
            "subject": str(saved_id), "saved_id": saved_id,
            "year": res.year, "month": res.month,
            "department": res.department,
        })
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse(content={"id": saved_id, "year": res.year, "month": res.month})


@router.get("/saved/export")
def export_database_route() -> FileResponse:
    """Скачать полную базу сохранённых месяцев (копия в указанное место)."""
    import time
    path = storage.export_database()
    timestamp = time.strftime("%Y-%m-%d")
    filename = f"med-roster-{timestamp}.db"
    return FileResponse(path, media_type="application/x-sqlite3",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/saved/import")
async def import_database_route(file: UploadFile = File(...)) -> JSONResponse:
    """Загрузить стороннюю базу ``med-roster.db`` и объединить с локальной."""
    data = await file.read()
    if not data:
        return JSONResponse(status_code=400, content={"error": "пустой файл"})
    if len(data) > MAX_UPLOAD_BYTES:
        return JSONResponse(status_code=413, content={
            "error": "файл слишком большой (максимум 20 МБ)"})
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".db", prefix="med-roster-import-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        added = storage.import_database(path)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=422, content={"error": str(exc)})
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return JSONResponse(content={"added": added})


@router.post("/saved/{saved_id}/load")
def load_saved(saved_id: int) -> JSONResponse:
    """Загрузить сохранённый месяц в новую сессию."""
    data = storage.get_saved(saved_id)
    if data is None:
        return JSONResponse(status_code=404, content={"error": "сохранение не найдено"})
    try:
        res = deserialize_result(data)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=422, content={"error": str(exc)})
    return _new_session(res)


@router.delete("/saved/{saved_id}")
def delete_saved_route(saved_id: int) -> JSONResponse:
    """Удалить сохранённый месяц."""
    data = storage.get_saved(saved_id)
    ok = storage.delete_saved(saved_id)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "сохранение не найдено"})
    try:
        webhooks.emit_event("month.deleted", {
            "subject": str(saved_id), "saved_id": saved_id,
            "year": (data or {}).get("year"),
            "month": (data or {}).get("month"),
        })
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse(content={"deleted": saved_id})


@router.post("/session/{sid}/generate")
def generate_route(sid: str,
                   year: int = Body(...),
                   month: int = Body(...),
                   copy_shifts: bool = Body(False)) -> JSONResponse:
    """Сгенерировать следующий месяц на основе текущего графика."""
    session = _get_session(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    try:
        new_res = generate_month(res, year, month, copy_shifts=copy_shifts)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})
    new_sid, payload = _new_session_payload(new_res)
    _emit_schedule_changed(new_res, new_sid, "generate")
    return JSONResponse(content=payload)


@router.post("/session/{sid}/cell")
def edit_cell(sid: str,
              row_index: int = Body(...),
              day: int = Body(...),
              value: str = Body("")) -> JSONResponse:
    """Изменить одну ячейку графика и пересчитать валидацию.

    ``row_index`` — исходный номер строки сотрудника (поле ``index`` из импорта),
    ``day`` — день месяца (1-based), ``value`` — новое значение ячейки
    (интервал времени, код статуса или пустая строка).
    """
    session = _get_session(sid)
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
    _emit_schedule_changed(res, sid, "cell")

    conflicts = check_all(res)
    session["conflicts"] = conflicts
    _autosave_draft(res)
    payload = _result_to_dict(res, conflicts)
    payload["session_id"] = sid
    return JSONResponse(content=payload)


@router.post("/session/{sid}/autocorrect")
def autocorrect_route(sid: str) -> JSONResponse:
    """Применить детерминированные исправления и пересчитать валидацию."""
    session = _get_session(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    fixes = autocorrect(res)
    _emit_schedule_changed(res, sid, "autocorrect")
    conflicts = check_all(res)
    session["conflicts"] = conflicts
    _autosave_draft(res)
    payload = _result_to_dict(res, conflicts)
    payload["session_id"] = sid
    payload["fixes"] = fixes
    return JSONResponse(content=payload)


@router.post("/session/{sid}/autofill")
def autofill_route(sid: str,
                   row_index: int = Body(...),
                   shift: str = Body(...),
                   mode: str = Body("workdays")) -> JSONResponse:
    """Заполнить пустые ячейки сотрудника заданной сменой.

    ``mode`` — ``"workdays"`` (только рабочие дни) или ``"empty"`` (все пустые).
    """
    session = _get_session(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    try:
        warnings = autofill(res, row_index, shift, mode)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})
    _emit_schedule_changed(res, sid, "autofill")
    conflicts = check_all(res)
    session["conflicts"] = conflicts
    _autosave_draft(res)
    payload = _result_to_dict(res, conflicts)
    payload["session_id"] = sid
    payload["warnings"] = res.warnings + warnings
    return JSONResponse(content=payload)


@router.post("/session/{sid}/copy")
def copy_route(sid: str,
               from_index: int = Body(...),
               to_index: int = Body(...)) -> JSONResponse:
    """Скопировать график одного сотрудника другому (синхронизация врач↔медсестра)."""
    session = _get_session(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    try:
        copy_schedule(res, from_index, to_index)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})
    _emit_schedule_changed(res, sid, "copy")
    conflicts = check_all(res)
    session["conflicts"] = conflicts
    _autosave_draft(res)
    payload = _result_to_dict(res, conflicts)
    payload["session_id"] = sid
    return JSONResponse(content=payload)


# --------------------------------------------------------------------------- #
#  Обновления приложения и необходимых компонентов
#  (POST-обновления — только локально / X-Admin-Token, см. AuthMiddleware)
# --------------------------------------------------------------------------- #
@router.get("/maintenance")
def maintenance() -> JSONResponse:
    try:
        return JSONResponse(content=updater.maintenance_status())
    except Exception as exc:  # сеть не должна ломать основной интерфейс
        return JSONResponse(status_code=503, content={"error": str(exc)})


@router.post("/maintenance/dependencies")
def maintenance_dependencies() -> JSONResponse:
    try:
        result = updater.update_dependencies()
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
    return JSONResponse(status_code=200 if result.get("ok") else 500, content=result)


@router.post("/maintenance/app")
def maintenance_app_update() -> JSONResponse:
    try:
        result = updater.install_app_update()
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
    if result.get("ok"):
        _schedule_shutdown()
    return JSONResponse(status_code=200 if result.get("ok") else 400, content=result)


@router.get("/export/xls/{sid}")
def export_xls_route(sid: str, org: Optional[str] = None,
                     dept: Optional[str] = None) -> Response:
    """Выгрузить исправленный график в бинарном формате Excel ``.xls``."""
    session = _get_session(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    content = export_xls(res, org=org or DEFAULT_ORG,
                         dept=dept if dept is not None else res.department)
    filename = "graph_%d-%02d.xls" % (res.year, res.month)
    return Response(
        content=content,
        media_type="application/vnd.ms-excel",
        headers={"Content-Disposition":
                 'attachment; filename="%s"' % filename},
    )


@router.get("/export/csv/{sid}")
def export_csv_route(sid: str) -> Response:
    """Выгрузить исправленный график в CSV."""
    session = _get_session(sid)
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


@router.get("/export/t13/{sid}")
def export_t13_route(sid: str, org: Optional[str] = None,
                     dept: Optional[str] = None) -> Response:
    """Сформировать табель Т-13 (печатный HTML)."""
    session = _get_session(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    html_text = export_t13_html(res, org=org or DEFAULT_ORG,
                                dept=dept if dept is not None else res.department)
    filename = "tabel_T13_%d-%02d.html" % (res.year, res.month)
    return Response(
        content=html_text,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition":
                 'attachment; filename="%s"' % filename},
    )


@router.get("/export/okud/{sid}")
def export_okud_route(sid: str, org: Optional[str] = None,
                      dept: Optional[str] = None) -> Response:
    """Сформировать табель ОКУД 0504421 (печатный HTML)."""
    session = _get_session(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    html_text = export_okud_html(res, org=org or DEFAULT_ORG,
                                 dept=dept if dept is not None else res.department)
    filename = "tabel_OKUD0504421_%d-%02d.html" % (res.year, res.month)
    return Response(
        content=html_text,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition":
                 'attachment; filename="%s"' % filename},
    )


@router.get("/export/signoff/{sid}")
def export_signoff_route(sid: str, org: Optional[str] = None,
                         dept: Optional[str] = None) -> Response:
    """Сформировать график на подпись (печатный HTML)."""
    session = _get_session(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    html_text = export_signoff_html(res, org=org or DEFAULT_ORG,
                                    dept=dept if dept is not None else res.department)
    filename = "graph_podpis_%d-%02d.html" % (res.year, res.month)
    return Response(
        content=html_text,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition":
                 'attachment; filename="%s"' % filename},
    )


# --------------------------------------------------------------------------- #
#  Синхронизация с МИС (Фаза 2): мастер-данные сотрудников, push/pull графиков
# --------------------------------------------------------------------------- #
@router.get("/employees")
def employees_directory(year: Optional[int] = None,
                        month: Optional[int] = None,
                        department: Optional[str] = None) -> JSONResponse:
    """Мастер-данные сотрудников из сохранённых месяцев (для кадровой МИС).

    Уникальные сотрудники по (ФИО, подразделение): должность, ставка,
    недельная норма и периоды, в которых сотрудник встречается.
    Фильтры: ``year``, ``month``, ``department``.
    """
    try:
        saved = storage.list_saved()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(exc)})
    out: Dict[str, Dict[str, Any]] = {}
    for item in saved:
        if year is not None and item["year"] != int(year):
            continue
        if month is not None and item["month"] != int(month):
            continue
        data = storage.get_saved(item["id"])
        if not data:
            continue
        dept = (data.get("department") or "").strip()
        if department is not None and dept != department.strip():
            continue
        period = "%04d-%02d" % (item["year"], item["month"])
        for e in data.get("employees", []):
            name = (e.get("name") or "").strip()
            if not name:
                continue
            key = name + "|" + dept
            rec = out.get(key)
            if rec is None:
                out[key] = {
                    "name": name,
                    "position": e.get("position", "") or "",
                    "rate": e.get("rate", 1.0),
                    "week_norm": e.get("week_norm"),
                    "department": dept,
                    "periods": [period],
                }
            elif period not in rec["periods"]:
                rec["periods"].append(period)
    employees = sorted(out.values(),
                       key=lambda r: (r["department"], r["name"]))
    return JSONResponse(content={"count": len(employees),
                                 "employees": employees})


@router.post("/employees/sync")
def employees_sync(payload: Dict[str, Any] = Body(...)) -> JSONResponse:
    """Синхронизация мастер-данных сотрудников (HR → МедГрафик).

    Тело: ``{year, month, employees: [{name, position?, rate?, week_norm?}],
    department?, session_id?, remove_missing?}``. Сотрудники сопоставляются
    по ФИО: новые добавляются, существующие обновляются. При
    ``remove_missing=true`` сотрудники, отсутствующие в списке, удаляются.
    Возвращает график периода (сессию) и отчёт синхронизации.
    """
    year = payload.get("year")
    month = payload.get("month")
    if not isinstance(year, int) or not isinstance(month, int) \
            or not (1 <= month <= 12):
        return JSONResponse(status_code=422,
                            content={"error": "укажите year и month (1-12)"})
    employees = payload.get("employees")
    if not isinstance(employees, list) or not employees:
        return JSONResponse(status_code=422,
                            content={"error": "укажите employees (список)"})

    session_id = payload.get("session_id")
    if session_id:
        session = _get_session(str(session_id))
        if session is None:
            return JSONResponse(status_code=404,
                                content={"error": "сессия не найдена"})
        sid = str(session_id)
        res: ImportResult = session["result"]
        if res.year != year or res.month != month:
            return JSONResponse(status_code=422, content={
                "error": "период сессии не совпадает с year/month"})
    else:
        found = storage.find_saved(year, month)
        if found is not None:
            res = deserialize_result(found["data"])
        else:
            res = create_manual_schedule(year, month)
        sid = uuid.uuid4().hex
        _sessions[sid] = {"result": res, "conflicts": check_all(res),
                          "at": time.time()}
        _gc_sessions()

    department = (payload.get("department") or "").strip()
    if department:
        res.department = department

    report: Dict[str, Any] = {"added": [], "updated": [],
                              "unchanged": [], "removed": []}
    by_name = {r.name: r for r in res.rows}
    seen = set()
    for e in employees:
        if not isinstance(e, dict):
            continue
        name = (e.get("name") or "").strip()
        if not name:
            continue
        seen.add(name)
        position = (e.get("position") or "").strip()
        try:
            rate = float(e.get("rate", 1.0) or 1.0)
        except (TypeError, ValueError):
            rate = 1.0
        if rate <= 0 or rate > 2:
            rate = 1.0
        week_norm = e.get("week_norm")
        if week_norm is not None and week_norm not in VALID_WEEK_NORMS:
            return JSONResponse(status_code=422, content={
                "error": "%s: недельная норма должна быть 30/33/36/39/40" % name})
        row = by_name.get(name)
        if row is None:
            if position and week_norm is None:
                week_norm, _r = classify(position)
            idx = max([r.index for r in res.rows], default=-1) + 1
            res.rows.append(EmployeeRow(index=idx, name=name,
                                        position=position, rate=rate,
                                        week_norm=week_norm))
            report["added"].append(name)
        else:
            changed = False
            if position and position != row.position:
                row.position = position
                if week_norm is None:
                    row.week_norm, _r = classify(position)
                    row.norm_rule = None
                changed = True
            if rate != row.rate:
                row.rate = rate
                changed = True
            if week_norm is not None and week_norm != row.week_norm:
                row.week_norm = int(week_norm)
                changed = True
            report["updated" if changed else "unchanged"].append(name)
    if payload.get("remove_missing"):
        for row in list(res.rows):
            if row.name not in seen:
                res.rows.remove(row)
                report["removed"].append(row.name)
    else:
        # кто есть в графике, но не пришёл от МИС (кандидаты на удаление)
        report["not_in_list"] = [r.name for r in res.rows if r.name not in seen]

    _emit_schedule_changed(res, sid, "employees.sync")
    return _refresh_session(sid, extra={"sync": report})


@router.get("/roster")
def roster_pull(year: int, month: int) -> JSONResponse:
    """Полный график сохранённого месяца (pull): сотрудники, дни, часы, конфликты."""
    found = storage.find_saved(year, month)
    if found is None:
        return JSONResponse(status_code=404,
                            content={"error": "за период график не сохранён"})
    res = deserialize_result(found["data"])
    conflicts = check_all(res)
    payload = _result_to_dict(res, conflicts)
    payload["saved_id"] = found["id"]
    return JSONResponse(content=payload)


@router.post("/roster")
def roster_push(payload: Dict[str, Any] = Body(...)) -> JSONResponse:
    """Загрузить график целиком (push от МИС) и провалидировать.

    Тело: ``{year, month, department?, employees: [{name, position?, rate?,
    week_norm?, days?: {"1": "8-15,48", ...}}], save?, org?, title?}``.
    При ``save=true`` график сразу сохраняется в базу (вебхук month.saved).
    """
    year = payload.get("year")
    month = payload.get("month")
    if not isinstance(year, int) or not isinstance(month, int) \
            or not (1 <= month <= 12):
        return JSONResponse(status_code=422,
                            content={"error": "укажите year и month (1-12)"})
    employees = payload.get("employees")
    if not isinstance(employees, list):
        return JSONResponse(status_code=422,
                            content={"error": "укажите employees (список)"})

    res = create_manual_schedule(year, month)
    res.department = (payload.get("department") or "").strip()
    for i, e in enumerate(employees):
        if not isinstance(e, dict):
            return JSONResponse(status_code=422,
                                content={"error": "employees[%d] не объект" % i})
        name = (e.get("name") or "").strip()
        if not name:
            return JSONResponse(status_code=422,
                                content={"error": "employees[%d]: укажите name" % i})
        position = (e.get("position") or "").strip()
        try:
            rate = float(e.get("rate", 1.0) or 1.0)
        except (TypeError, ValueError):
            rate = 1.0
        if rate <= 0 or rate > 2:
            return JSONResponse(status_code=422,
                                content={"error": "employees[%d]: неверная ставка" % i})
        week_norm = e.get("week_norm")
        if week_norm is not None and week_norm not in VALID_WEEK_NORMS:
            return JSONResponse(status_code=422, content={
                "error": "employees[%d]: норма 30/33/36/39/40" % i})
        if position and week_norm is None:
            week_norm, _r = classify(position)
        row = EmployeeRow(index=i, name=name, position=position,
                          rate=rate, week_norm=week_norm)
        days = e.get("days") or {}
        if not isinstance(days, dict):
            return JSONResponse(status_code=422,
                                content={"error": "employees[%d].days не объект" % i})
        for dk, dv in days.items():
            try:
                day = int(dk)
            except (TypeError, ValueError):
                return JSONResponse(status_code=422, content={
                    "error": "employees[%d].days: день %r" % (i, dk)})
            if not (1 <= day <= res.day_count):
                return JSONResponse(status_code=422, content={
                    "error": "employees[%d].days: день %d вне месяца" % (i, day)})
            raw = ("" if dv is None else str(dv)).strip()
            if raw == "":
                continue
            row.raw_cells[day] = raw
            row.parsed[day] = parse_cell(raw)
        row.total_hours = sum(p.total_hours for p in row.parsed.values())
        res.rows.append(row)

    sid, out = _new_session_payload(res)
    if payload.get("save"):
        try:
            saved_id = storage.save_month(
                year, month, payload.get("org") or DEFAULT_ORG,
                serialize_result(res), title=(payload.get("title") or ""))
            storage.clear_draft()
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(status_code=500, content={"error": str(exc)})
        try:
            webhooks.emit_event("month.saved", {
                "subject": str(saved_id), "saved_id": saved_id,
                "year": year, "month": month,
                "department": res.department,
                "employee_count": len(res.rows),
                "source": "push",
            })
        except Exception:  # noqa: BLE001
            pass
        out["saved_id"] = saved_id
    return JSONResponse(content=out)


# --------------------------------------------------------------------------- #
#  Вебхуки: уведомления МИС об изменениях (Фаза 2)
# --------------------------------------------------------------------------- #
def _webhook_scope(request: Request) -> Optional[int]:
    """Ограничение доступа к вебхукам: id тенанта или None (все).

    Локальный UI и X-Admin-Token работают со всеми вебхуками; API-ключ —
    только с вебхуками своего тенанта.
    """
    info = request.scope.get("mrauth", {})
    if info.get("status") == "authorized" and info.get("tenant"):
        return api_auth.find_tenant_id(info["tenant"])
    return None


@router.get("/webhooks")
def webhooks_list(request: Request) -> JSONResponse:
    """Список вебхуков (админ — все, ключ — только своего тенанта)."""
    return JSONResponse(content={
        "webhooks": storage.list_webhooks(_webhook_scope(request))})


@router.post("/webhooks")
def webhooks_create(request: Request,
                    url: str = Body(..., embed=True),
                    events: Optional[List[str]] = Body(None, embed=True),
                    tenant: str = Body("", embed=True)) -> JSONResponse:
    """Зарегистрировать вебхук; секрет доставки возвращается один раз.

    ``events`` — список событий (по умолчанию все, кроме ``webhook.test``).
    Ключ может регистрировать вебхуки только для своего тенанта; локальный
    администратор указывает ``tenant`` явно.
    """
    url = (url or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return JSONResponse(status_code=422, content={
            "error": "url должен начинаться с http:// или https://"})
    events = events or [e for e in webhooks.KNOWN_EVENTS if e != "webhook.test"]
    unknown = [e for e in events if e not in webhooks.KNOWN_EVENTS]
    if unknown:
        return JSONResponse(status_code=422, content={
            "error": "неизвестные события: %s (доступны: %s)" % (
                ", ".join(unknown), ", ".join(webhooks.KNOWN_EVENTS))})

    info = request.scope.get("mrauth", {})
    if info.get("status") == "authorized":
        tenant_id = api_auth.find_tenant_id(info.get("tenant") or "")
        if tenant_id is None:
            return JSONResponse(status_code=500,
                                content={"error": "тенант ключа не найден"})
    else:
        tenant_name = (tenant or "").strip()
        if not tenant_name:
            return JSONResponse(status_code=422, content={
                "error": "укажите tenant (название клиники/МИС)"})
        tenant_id = api_auth.ensure_tenant(tenant_name)

    secret = "mrwh_" + secrets.token_hex(20)
    try:
        webhook_id = storage.create_webhook(tenant_id, url, secret, events)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(exc)})
    return JSONResponse(content={
        "id": webhook_id, "url": url, "events": events,
        "is_active": True, "secret": secret,
        "note": "сохраните секрет доставки: он показывается один раз",
    })


@router.delete("/webhooks/{webhook_id}")
def webhooks_delete(request: Request, webhook_id: int) -> JSONResponse:
    """Удалить вебхук."""
    ok = storage.delete_webhook(webhook_id, tenant_id=_webhook_scope(request))
    if not ok:
        return JSONResponse(status_code=404, content={"error": "вебхук не найден"})
    return JSONResponse(content={"id": webhook_id, "deleted": True})


@router.post("/webhooks/{webhook_id}/activate")
def webhooks_activate(request: Request, webhook_id: int,
                      active: bool = Body(True, embed=True)) -> JSONResponse:
    """Включить/отключить вебхук."""
    ok = storage.set_webhook_active(webhook_id, active,
                                    tenant_id=_webhook_scope(request))
    if not ok:
        return JSONResponse(status_code=404, content={"error": "вебхук не найден"})
    return JSONResponse(content={"id": webhook_id, "is_active": bool(active)})


@router.post("/webhooks/{webhook_id}/test")
def webhooks_test(request: Request, webhook_id: int) -> JSONResponse:
    """Отправить тестовое событие ``webhook.test`` в этот вебхук."""
    hook = storage.get_webhook(webhook_id)
    scope_id = _webhook_scope(request)
    if hook is None or (scope_id is not None
                        and hook["tenant_id"] != scope_id):
        return JSONResponse(status_code=404, content={"error": "вебхук не найден"})
    if not hook["is_active"]:
        return JSONResponse(status_code=422, content={"error": "вебхук отключён"})
    queued = webhooks.emit_event(
        "webhook.test", {"subject": "test:%d" % webhook_id},
        only_webhook_id=webhook_id)
    return JSONResponse(content={"id": webhook_id, "queued": queued})


# --------------------------------------------------------------------------- #
#  Экспорт: HL7 FHIR R4 и подписанный пакет (Фаза 3)
# --------------------------------------------------------------------------- #
# Смещение часового пояса: ±ЧЧ:ММ, часы 00-14 (реальные UTC-смещения).
_TZ_RE = re.compile(r"^[+-](?:0\d|1[0-4]):[0-5]\d$")


@router.get("/export/fhir/{sid}")
def export_fhir_route(sid: str, tz: str = "+03:00") -> Response:
    """Экспорт графика в HL7 FHIR R4 (Bundle: Practitioner/Schedule/Slot).

    ``tz`` — смещение часового пояса для времён слотов, например ``+03:00``
    (Москва) или ``+04:00`` (Саратов).
    """
    session = _get_session(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    # «+» в query-параметре декодируется в пробел (tz=+04:00 -> " 04:00"),
    # поэтому сначала нормализуем: «04:00» трактуем как «+04:00».
    tz = (tz or "").strip()
    if re.match(r"^(?:0\d|1[0-4]):[0-5]\d$", tz):
        tz = "+" + tz
    if not _TZ_RE.match(tz):
        return JSONResponse(status_code=422,
                            content={"error": "tz должен быть вида +03:00 "
                                              "(в query кодируйте как %2B03:00)"})
    bundle = export_fhir_bundle(res, tz=tz)
    filename = "fhir_%d-%02d.json" % (res.year, res.month)
    return Response(
        content=json.dumps(bundle, ensure_ascii=False),
        media_type="application/fhir+json",
        headers={"Content-Disposition":
                 'attachment; filename="%s"' % filename},
    )


@router.get("/export/signed/{sid}")
def export_signed_route(sid: str, org: Optional[str] = None,
                        dept: Optional[str] = None,
                        signer: Optional[str] = None) -> Response:
    """Подписанный пакет экспорта: ZIP со всеми формами + manifest + подпись.

    В архиве: график (CSV + XLS), Т-13, ОКУД 0504421, график на подпись,
    ``manifest.json`` (контрольные суммы и HMAC-подписи каждого файла) и
    ``manifest.sig`` (подпись манифеста). Проверить пакет можно эндпоинтом
    ``POST /export/verify``.
    """
    session = _get_session(sid)
    if session is None:
        return JSONResponse(status_code=404, content={"error": "сессия не найдена"})
    res: ImportResult = session["result"]
    content = export_signed_zip(res, org=org or DEFAULT_ORG,
                                dept=dept if dept is not None else res.department,
                                signer=signer or "")
    filename = "med-roster_%d-%02d_signed.zip" % (res.year, res.month)
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition":
                 'attachment; filename="%s"' % filename},
    )


@router.post("/export/verify")
async def export_verify(file: UploadFile = File(...)) -> JSONResponse:
    """Проверить подписанный ZIP-пакет (контрольные суммы и подписи)."""
    data = await file.read()
    if not data:
        return JSONResponse(status_code=400, content={"error": "пустой файл"})
    if len(data) > MAX_UPLOAD_BYTES:
        return JSONResponse(status_code=413, content={
            "error": "файл слишком большой (максимум 20 МБ)"})
    try:
        report = verify_signed_zip(data)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=422,
                            content={"error": "не подписанный ZIP-пакет: %s" % exc})
    return JSONResponse(content=report)


# --------------------------------------------------------------------------- #
#  Управление API-ключами и аудит (только локально / X-Admin-Token)
# --------------------------------------------------------------------------- #
@router.get("/keys")
def list_keys_route() -> JSONResponse:
    """Список API-ключей (без секретов: префиксы и метаданные)."""
    return JSONResponse(content={"keys": api_auth.list_keys()})


@router.post("/keys")
def create_key_route(tenant: str = Body(..., embed=True),
                     label: str = Body("", embed=True)) -> JSONResponse:
    """Выпустить новый API-ключ для тенанта (клиники/МИС).

    Полный ключ возвращается ровно один раз — сохранить его в МИС сразу;
    восстановлению он не подлежит (только перевыпуск).
    """
    tenant = (tenant or "").strip()
    if not tenant:
        return JSONResponse(status_code=422,
                            content={"error": "укажите название тенанта (клиники/МИС)"})
    try:
        info = api_auth.create_key(tenant, label=label)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(exc)})
    return JSONResponse(content=info)


@router.delete("/keys/{key_id}")
def revoke_key_route(key_id: int) -> JSONResponse:
    """Отозвать ключ (обратимо через /keys/{id}/activate)."""
    ok = api_auth.revoke_key(key_id)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "ключ не найден"})
    return JSONResponse(content={"id": key_id, "revoked": True})


@router.post("/keys/{key_id}/activate")
def activate_key_route(key_id: int) -> JSONResponse:
    """Восстановить отозванный ключ."""
    ok = api_auth.activate_key(key_id)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "ключ не найден"})
    return JSONResponse(content={"id": key_id, "activated": True})


@router.get("/keys/tenants")
def list_tenants_route() -> JSONResponse:
    """Список тенантов с числом активных ключей."""
    return JSONResponse(content={"tenants": api_auth.list_tenants()})


@router.get("/audit")
def audit_route(limit: int = 100,
                auth_status: Optional[str] = None,
                key_id: Optional[int] = None) -> JSONResponse:
    """Последние записи аудита (новые сверху).

    Фильтры: ``auth_status`` (authorized / anonymous_local / anonymous /
    rejected_bad_key / rejected_no_key / rate_limited / forbidden_remote),
    ``key_id`` — только запросы конкретного ключа.
    """
    limit = max(1, min(int(limit or 100), 1000))
    return JSONResponse(content={
        "entries": audit_log.recent(limit=limit, auth_status=auth_status,
                                    api_key_id=key_id),
    })


@router.get("/audit/stats")
def audit_stats_route() -> JSONResponse:
    """Сводка аудита: счётчики по результатам авторизации, топ тенантов."""
    return JSONResponse(content=audit_log.stats())


@router.delete("/audit")
def audit_clear_route(older_than_days: Optional[int] = None) -> JSONResponse:
    """Очистить аудит (весь или старше N дней)."""
    removed = audit_log.clear(older_than_days=older_than_days)
    return JSONResponse(content={"removed": removed})


# --------------------------------------------------------------------------- #
#  Подключение роутера и статики
# --------------------------------------------------------------------------- #
# /api/v1 — контракт для внешних систем (OpenAPI-схема описывает только его);
# /api    — прежние пути UI и обратной совместимости (в схему не входят).
app.include_router(router, prefix="/api/v1")
app.include_router(router, prefix="/api", include_in_schema=False)


@app.get("/", include_in_schema=False)  # UI-страница, не часть API-контракта
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
