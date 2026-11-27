# -*- coding: utf-8 -*-
"""Тесты релиза 0.12.0: завершение интеграционного слоя API.

Проверяется:
  * права API-ключей (scopes: read/write), включая ключи до 0.12.0;
  * идемпотентность push/sync (заголовок Idempotency-Key);
  * стабильный ID сотрудника (employee_id): push/pull/sync/remove_missing;
  * идемпотентное сохранение (upsert по периоду и подразделению) и фильтр
    pull по подразделению;
  * история доставок вебхуков и повтор неудачных (replay);
  * выгрузка аудита в CSV (локально только);
  * регрессии багов 0.12.0: пре-валидация sync без частичного применения,
    FHIR-слоты неявок (24:00 -> следующие сутки), ограниченное чтение
    загружаемых файлов.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import app.main as main
from app.core import api_auth, config, storage
from app.services import webhooks
from fastapi.testclient import TestClient

LOCAL = ("127.0.0.1", 50000)
REMOTE = ("10.0.0.5", 50000)


class _FakeResponse:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDROSTER_DATA_DIR", str(tmp_path))
    api_auth.reset_cache()
    main._sessions.clear()
    main._idempotency.clear()
    webhooks.reset()
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 10000)
    monkeypatch.setattr(config, "HEAVY_RATE_LIMIT_PER_MIN", 10000)
    monkeypatch.setattr(webhooks, "RETRY_DELAY", 0.05)
    monkeypatch.setattr(webhooks, "_urlopen",
                        lambda req, timeout=None: _FakeResponse(200))
    yield
    api_auth.reset_cache()
    main._sessions.clear()
    main._idempotency.clear()
    webhooks.reset()


def _local():
    return TestClient(main.app, client=LOCAL)


def _remote():
    return TestClient(main.app, client=REMOTE)


def _push(client, **over):
    body = {"year": 2026, "month": 11, "department": "УПО",
            "employees": [
                {"name": "Иванова И.И.", "employee_id": "Т-001",
                 "position": "Вр. педиатр участковый",
                 "days": {"2": "8-15,48"}},
                {"name": "Петров П.П.", "position": "Санитарка",
                 "rate": 0.5, "days": {"2": "8-14,36"}},
            ]}
    body.update(over)
    return client.post("/api/v1/roster", json=body)


# --------------------------------------------------------------------------- #
#  Права ключей (scopes)
# --------------------------------------------------------------------------- #
def test_key_scopes_read_only():
    """Ключ только с правом read: GET проходит, POST — 403."""
    info = api_auth.create_key("МИС Читатель", scopes=["read"])
    remote = _remote()
    h = {"X-API-Key": info["key"]}
    assert remote.get("/api/v1/health", headers=h).status_code == 200
    assert remote.get("/api/v1/roster?year=2026&month=11",
                      headers=h).status_code == 404  # не сохранён, но доступ есть
    r = remote.post("/api/v1/roster", headers=h,
                    json={"year": 2026, "month": 11, "employees": []})
    assert r.status_code == 403
    assert "read" in r.json()["error"] or "write" in r.json()["error"]


def test_key_scopes_write_only():
    """Ключ только с правом write: POST проходит, GET — 403."""
    info = api_auth.create_key("МИС Писатель", scopes=["write"])
    remote = _remote()
    h = {"X-API-Key": info["key"]}
    resp = remote.post("/api/v1/roster", headers=h, json={
        "year": 2026, "month": 11,
        "employees": [{"name": "Сидоров С.С."}]})
    assert resp.status_code == 200
    assert remote.get("/api/v1/health", headers=h).status_code == 403
    assert remote.get("/api/v1/roster?year=2026&month=11",
                      headers=h).status_code == 403


def test_key_scopes_legacy_full():
    """Ключ без scopes (выпущен до 0.12.0): оба права — поведение не меняется."""
    info = api_auth.create_key("МИС Старая")
    assert info["scopes"] == ["read", "write"]
    remote = _remote()
    h = {"X-API-Key": info["key"]}
    assert remote.get("/api/v1/health", headers=h).status_code == 200
    assert remote.post("/api/v1/roster", headers=h, json={
        "year": 2026, "month": 11,
        "employees": [{"name": "Сидоров С.С."}]}).status_code == 200


def test_key_scopes_via_route():
    """POST /keys со scopes; список ключей показывает права."""
    client = _local()
    r = client.post("/api/v1/keys", json={
        "tenant": "МИС РО", "label": "только чтение", "scopes": ["read"]})
    assert r.status_code == 200
    assert r.json()["scopes"] == ["read"]

    keys = client.get("/api/v1/keys").json()["keys"]
    by_prefix = {k["prefix"]: k for k in keys}
    assert by_prefix[r.json()["prefix"]]["scopes"] == ["read"]

    # неизвестные права отбрасываются; пусто -> полные права
    r = client.post("/api/v1/keys", json={
        "tenant": "МИС Мусор", "scopes": ["admin", ""]})
    assert r.json()["scopes"] == ["read", "write"]


# --------------------------------------------------------------------------- #
#  Идемпотентность push/sync
# --------------------------------------------------------------------------- #
def test_push_idempotency():
    """Повтор push с тем же Idempotency-Key возвращает сохранённый ответ."""
    client = _local()
    h = {"Idempotency-Key": "req-001"}
    r1 = client.post(
        "/api/v1/roster", json={
            "year": 2026, "month": 11, "department": "УПО",
            "employees": [{"name": "Иванова И.И."}]}, headers=h)
    assert r1.status_code == 200
    sid = r1.json()["session_id"]
    assert "idempotency-replayed" not in r1.headers

    r2 = client.post("/api/v1/roster", json={
        "year": 2026, "month": 11, "department": "УПО",
        "employees": [{"name": "ДРУГОЙ СПИСОК"}]}, headers=h)
    assert r2.status_code == 200
    assert r2.json()["session_id"] == sid           # та же сессия, не новая
    assert r2.headers.get("idempotency-replayed") == "true"
    # тело ответа — сохранённое (первый список), а не «ДРУГОЙ СПИСОК»
    assert r2.json()["employees"][0]["name"] == "Иванова И.И."

    # другой ключ — новый запрос
    r3 = client.post("/api/v1/roster", json={
        "year": 2026, "month": 11, "department": "УПО",
        "employees": [{"name": "ДРУГОЙ СПИСОК"}]},
        headers={"Idempotency-Key": "req-002"})
    assert r3.json()["session_id"] != sid
    assert r3.json()["employees"][0]["name"] == "ДРУГОЙ СПИСОК"


def test_push_idempotency_subject_isolation():
    """Один и тот же ключ идемпотентности у разных клиентов не пересекается."""
    h = {"Idempotency-Key": "same-key"}
    r1 = _local().post("/api/v1/roster", json={
        "year": 2026, "month": 11, "employees": [{"name": "Локальный"}]},
                       headers=h)
    r2 = _remote().post("/api/v1/roster", json={
        "year": 2026, "month": 11, "employees": [{"name": "Внешний"}]},
                        headers=h)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["session_id"] != r2.json()["session_id"]
    assert r2.json()["employees"][0]["name"] == "Внешний"


def test_sync_idempotency():
    """Повтор sync с тем же ключом не применяет список второй раз."""
    client = _local()
    _push(client, save=True)
    body = {"year": 2026, "month": 11,
            "employees": [{"employee_id": "Т-001", "name": "Иванова И.И.",
                           "position": "Врач-педиатр"}]}
    h = {"Idempotency-Key": "sync-001"}
    r1 = client.post("/api/v1/employees/sync", json=body, headers=h)
    assert r1.status_code == 200
    assert r1.json()["sync"]["updated"] == ["Иванова И.И."]
    sid = r1.json()["session_id"]

    r2 = client.post("/api/v1/employees/sync", json=body, headers=h)
    assert r2.status_code == 200
    assert r2.headers.get("idempotency-replayed") == "true"
    assert r2.json()["session_id"] == sid
    # сохранённый отчёт (первое применение), а не «unchanged» от второго
    assert r2.json()["sync"]["updated"] == ["Иванова И.И."]


def test_sync_prevalidation_no_partial_apply():
    """Регрессия 0.12.0: мусор в середине списка не применяется частично.

    Раньше ставка/норма проверялись в цикле применения: невалидная запись
    возвращала 422 ПОСЛЕ добавления предыдущих сотрудников в сессию.
    """
    client = _local()
    sid = _push(client).json()["session_id"]

    r = client.post("/api/v1/employees/sync", json={
        "session_id": sid, "year": 2026, "month": 11,
        "employees": [
            {"name": "Новый Н.Н.", "position": "Регистратор"},
            {"name": "Плохой П.П.", "rate": 5},      # мусор во второй записи
        ]})
    assert r.status_code == 422

    # сессия НЕ изменилась: повторная синхронизация без мусора видит
    # «Новый Н.Н.» как нового (не как уже добавленного)
    r2 = client.post("/api/v1/employees/sync", json={
        "session_id": sid, "year": 2026, "month": 11,
        "employees": [{"name": "Новый Н.Н.", "position": "Регистратор"}]})
    assert r2.status_code == 200
    assert r2.json()["sync"]["added"] == ["Новый Н.Н."]


def test_sync_bad_rate_rejected():
    """Регрессия 0.12.0: sync больше не превращает мусорную ставку в 1.0."""
    client = _local()
    r = client.post("/api/v1/employees/sync", json={
        "year": 2026, "month": 11,
        "employees": [{"name": "А", "rate": 0},
                      {"name": "Б", "rate": 2.5}]})
    assert r.status_code == 422
    # null-ставка по-прежнему означает «не задана» -> 1.0
    r = client.post("/api/v1/employees/sync", json={
        "year": 2026, "month": 11,
        "employees": [{"name": "В", "rate": None}]})
    assert r.status_code == 200
    assert r.json()["employees"][0]["rate"] == 1.0


# --------------------------------------------------------------------------- #
#  Стабильный ID сотрудника (employee_id)
# --------------------------------------------------------------------------- #
def test_push_pull_employee_id():
    client = _local()
    sid = _push(client, save=True).json()["session_id"]
    data = client.get("/api/v1/roster?year=2026&month=11").json()
    emp = {e["name"]: e for e in data["employees"]}
    assert emp["Иванова И.И."]["employee_id"] == "Т-001"
    assert emp["Петров П.П."]["employee_id"] == ""


def test_sync_renames_by_employee_id():
    """ФИО сменилось, табельный номер тот же: sync обновляет имя, график цел."""
    client = _local()
    _push(client, save=True)
    r = client.post("/api/v1/employees/sync", json={
        "year": 2026, "month": 11,
        "employees": [{"employee_id": "Т-001",
                       "name": "Иванова-Петрова И.И."}]}).json()
    assert r["sync"]["updated"] == ["Иванова-Петрова И.И."]
    assert r["sync"]["added"] == []
    emp = r["employees"][0]
    assert emp["name"] == "Иванова-Петрова И.И."
    assert emp["employee_id"] == "Т-001"
    assert emp["position"] == "Вр. педиатр участковый"   # не затёрто
    assert emp["days"]["2"]["raw"] == "8-15,48"          # график цел


def test_sync_fallback_by_name():
    """Без employee_id сопоставление по ФИО — как раньше (обратная совместимость)."""
    client = _local()
    _push(client, save=True)
    r = client.post("/api/v1/employees/sync", json={
        "year": 2026, "month": 11,
        "employees": [{"name": "Иванова И.И.",
                       "position": "Врач-педиатр"}]}).json()
    assert r["sync"]["updated"] == ["Иванова И.И."]
    assert r["sync"]["added"] == []


def test_sync_remove_missing_keeps_id_matched():
    """remove_missing не удаляет сотрудника, пришедшего с другим ФИО,
    но с тем же табельным номером."""
    client = _local()
    _push(client, save=True)
    r = client.post("/api/v1/employees/sync", json={
        "year": 2026, "month": 11, "remove_missing": True,
        "employees": [{"employee_id": "Т-001",
                       "name": "Иванова-Петрова И.И."}]}).json()
    assert r["sync"]["removed"] == ["Петров П.П."]
    assert [e["name"] for e in r["employees"]] == ["Иванова-Петрова И.И."]


# --------------------------------------------------------------------------- #
#  Upsert сохранений и фильтр pull по подразделению
# --------------------------------------------------------------------------- #
def test_push_save_upsert():
    """Повторный push с save того же периода/отделения обновляет запись."""
    client = _local()
    r1 = _push(client, save=True).json()
    r2 = _push(client, save=True).json()
    assert r1["saved_id"] == r2["saved_id"]
    saved = client.get("/api/saved").json()["saved"]
    assert len(saved) == 1                          # нет дублей периода

    # другое подразделение — отдельная запись
    r3 = _push(client, save=True, department="Хозчасть").json()
    assert r3["saved_id"] != r1["saved_id"]
    assert len(client.get("/api/saved").json()["saved"]) == 2


def test_pull_department_filter():
    client = _local()
    _push(client, save=True)                                   # УПО
    _push(client, save=True, department="Хозчасть")
    r = client.get("/api/v1/roster?year=2026&month=11&department=" + "УПО")
    assert r.status_code == 200
    assert r.json()["department"] == "УПО"
    r = client.get("/api/v1/roster?year=2026&month=11&department=Хозчасть")
    assert r.json()["department"] == "Хозчасть"
    # без фильтра — самое свежее сохранение периода (Хозчасть, оно позже)
    r = client.get("/api/v1/roster?year=2026&month=11")
    assert r.json()["department"] == "Хозчасть"
    r = client.get("/api/v1/roster?year=2026&month=11&department=Нет")
    assert r.status_code == 404


def test_ui_save_upsert():
    """Кнопка «Сохранить месяц» дважды: одна запись, created=False второй раз."""
    client = _local()
    sid = _push(client).json()["session_id"]
    r1 = client.post("/api/session/%s/save" % sid,
                     json={"org": "ОРГ", "dept": "УПО", "title": ""}).json()
    r2 = client.post("/api/session/%s/save" % sid,
                     json={"org": "ОРГ", "dept": "УПО", "title": ""}).json()
    assert r1["id"] == r2["id"]
    assert r1["created"] is True and r2["created"] is False
    assert len(client.get("/api/saved").json()["saved"]) == 1


# --------------------------------------------------------------------------- #
#  История доставок вебхуков и replay
# --------------------------------------------------------------------------- #
def _hook(events=("month.saved", "month.updated")):
    r = _local().post("/api/v1/webhooks", json={
        "url": "https://mis.example.local/hook", "tenant": "МИС Тест",
        "events": list(events)})
    assert r.status_code == 200
    return r.json()


def test_delivery_history_recorded(monkeypatch):
    """Успешная и неудачная доставки попадают в историю с итогом попыток."""
    info = _hook()
    client = _local()

    # успешная доставка
    _push(client, save=True)                       # month.saved
    assert webhooks.wait_delivered()
    hist = client.get("/api/v1/webhooks/%d/deliveries" % info["id"]).json()
    items = hist["deliveries"]
    assert len(items) == 1
    assert items[0]["event"] == "month.saved"
    assert items[0]["ok"] is True
    assert items[0]["attempts"] == 1
    assert items[0]["status"] == 200

    # неудачная: 2 попытки, ok=False
    def failing(req, timeout=None):
        raise OSError("net down")
    monkeypatch.setattr(webhooks, "_urlopen", failing)
    # тот же период и подразделение: upsert -> month.updated (не month.saved)
    _push(client, save=True)
    assert webhooks.wait_delivered()
    hist = client.get("/api/v1/webhooks/%d/deliveries" % info["id"],
                      params={"failed": "true"}).json()["deliveries"]
    assert len(hist) == 1
    assert hist[0]["ok"] is False
    assert hist[0]["attempts"] == 2                # 1-я + повтор
    assert hist[0]["event"] == "month.updated"


def test_replay_route(monkeypatch):
    """Replay повторяет неудачную доставку с новым id."""
    calls = []

    def fake(req, timeout=None):
        calls.append(json.loads(req.data.decode("utf-8"))
                     if isinstance(req.data, bytes) else req.data)
        return _FakeResponse(200)

    info = _hook()
    client = _local()

    def failing(req, timeout=None):
        raise OSError("net down")

    monkeypatch.setattr(webhooks, "_urlopen", failing)
    _push(client, save=True)
    assert webhooks.wait_delivered()
    failed = client.get("/api/v1/webhooks/%d/deliveries" % info["id"],
                        params={"failed": "true"}).json()["deliveries"][0]

    # повтор — доставка проходит
    monkeypatch.setattr(webhooks, "_urlopen", fake)
    r = client.post("/api/v1/webhooks/%d/replay" % info["id"],
                    json={"delivery_id": failed["delivery_id"]})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["delivery_id"] != failed["delivery_id"]
    assert webhooks.wait_delivered()
    assert len(calls) == 1
    assert calls[0]["event"] == "month.saved"      # исходный payload

    # исходная запись истории не изменилась
    still = client.get("/api/v1/webhooks/%d/deliveries" % info["id"],
                       params={"failed": "true"}).json()["deliveries"]
    assert len(still) == 1 and still[0]["ok"] is False


def test_replay_route_errors():
    """Replay: неизвестная доставка/вебхук — 404, чужой тенант — 404."""
    client = _local()
    info = _hook()
    r = client.post("/api/v1/webhooks/%d/replay" % info["id"],
                    json={"delivery_id": "nope"})
    assert r.status_code == 404
    r = client.post("/api/v1/webhooks/999/replay",
                    json={"delivery_id": "any"})
    assert r.status_code == 404


def test_deliveries_tenant_isolation():
    """Ключ видит историю только своего тенанта; чужая — 404."""
    client = _local()
    info = _hook()                                  # тенант «МИС Тест»
    _push(client, save=True)
    assert webhooks.wait_delivered()

    other = api_auth.create_key("МИС Чужая")
    remote = _remote()
    h = {"X-API-Key": other["key"]}
    r = remote.get("/api/v1/webhooks/%d/deliveries" % info["id"], headers=h)
    assert r.status_code == 404                     # чужой вебхук = несуществующий
    r = remote.post("/api/v1/webhooks/%d/replay" % info["id"],
                    headers=h, json={"delivery_id": "whatever"})
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
#  Аудит: выгрузка в CSV
# --------------------------------------------------------------------------- #
def test_audit_export_csv():
    client = _local()
    _push(client)
    r = client.get("/api/audit/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers.get("content-disposition", "")
    text = r.content.decode("utf-8-sig")            # BOM съеден
    assert r.content.startswith(b"\xef\xbb\xbf")    # ...но он там был (Excel)
    lines = [l for l in text.split("\r\n") if l.strip()]
    assert lines[0].split(";")[0] == "id"
    # наши запросы попали в выгрузку
    assert any("/api/v1/roster" in l for l in lines[1:])
    # фильтр по результату авторизации
    r = client.get("/api/audit/export", params={"auth_status": "anonymous_local"})
    text2 = r.content.decode("utf-8-sig")
    lines2 = [l for l in text2.split("\r\n") if l.strip()]
    assert len(lines2) >= 2
    assert all("anonymous_local" in l for l in lines2[1:])


def test_audit_export_local_only():
    """/audit/** доступен только локальному администратору."""
    info = api_auth.create_key("МИС Аудит")
    remote = _remote()
    r = remote.get("/api/v1/audit/export",
                   headers={"X-API-Key": info["key"]})
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
#  OpenAPI-схема: Pydantic-модели
# --------------------------------------------------------------------------- #
def test_openapi_models():
    schema = _local().get("/api/openapi.json").json()
    comps = schema["components"]["schemas"]
    assert "RosterPushIn" in comps
    assert "EmployeeSyncIn" in comps
    assert "WebhookCreateIn" in comps
    assert "KeyCreateIn" in comps
    emp = comps["EmployeeIn"]
    assert emp["required"] == ["name"]
    assert "employee_id" in emp["properties"]
    roster = comps["RosterPushIn"]
    assert roster["properties"]["year"]["minimum"] == 1991
    assert roster["properties"]["month"]["maximum"] == 12


# --------------------------------------------------------------------------- #
#  Регрессии: FHIR 24:00 и ограниченное чтение загрузок
# --------------------------------------------------------------------------- #
def test_fhir_absence_slot_rolls_to_next_day():
    """Регрессия 0.12.0: слот неявки «весь день» не кончается в T24:00:00.

    30 ноября + 24 часа = 1 декабря 00:00 (FHIR не допускает 24:00).
    """
    client = _local()
    sid = client.post("/api/v1/roster", json={
        "year": 2026, "month": 11,
        "employees": [{"name": "Иванова И.И.",
                       "days": {"30": "О"}}]}).json()["session_id"]
    bundle = client.get("/api/v1/export/fhir/%s" % sid).json()
    slots = [e["resource"] for e in bundle["entry"]
            if e["resource"]["resourceType"] == "Slot"]
    assert len(slots) == 1
    assert slots[0]["start"] == "2026-11-30T00:00:00+03:00"
    assert slots[0]["end"] == "2026-12-01T00:00:00+03:00"
    assert slots[0]["status"] == "busy-unavailable"


def test_upload_size_declared_before_read():
    """Размер проверяется ДО чтения: файл с size > лимита не читается."""
    class ExplodingUpload:
        filename = "big.xls"
        size = main.MAX_UPLOAD_BYTES + 1

        async def read(self, size=-1):
            raise AssertionError("read() не должен вызываться")

    import asyncio
    resp = asyncio.run(main.import_file(ExplodingUpload()))
    assert resp.status_code == 413
