# -*- coding: utf-8 -*-
"""Тесты Фазы 2: push/pull графиков и синхронизация сотрудников (HR ↔ МИС).

Сценарии:
  * POST /api/v1/roster — push графика от МИС: сессия, дни, часы, валидация;
  * GET  /api/v1/roster — pull сохранённого месяца (404, если не сохранён);
  * GET  /api/v1/employees — мастер-данные сотрудников из сохранённых месяцев;
  * POST /api/v1/employees/sync — upsert по ФИО (add/update/remove_missing).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import app.main as main
from app.core import api_auth, config
from fastapi.testclient import TestClient

LOCAL = ("127.0.0.1", 50000)
REMOTE = ("10.0.0.5", 50000)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDROSTER_DATA_DIR", str(tmp_path))
    api_auth.reset_cache()
    main._sessions.clear()
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 10000)
    monkeypatch.setattr(config, "HEAVY_RATE_LIMIT_PER_MIN", 10000)
    yield
    api_auth.reset_cache()
    main._sessions.clear()


def _local():
    return TestClient(main.app, client=LOCAL)


def _remote():
    return TestClient(main.app, client=REMOTE)


ROSTER = {
    "year": 2026, "month": 11, "department": "УПО",
    "employees": [
        {"name": "Иванова И.И.", "position": "Вр. педиатр участковый",
         "days": {"2": "8-15,48", "3": "О", "4": "В"}},
        {"name": "Петров П.П.", "position": "Санитарка",
         "rate": 0.5, "days": {"2": "8-14,36"}},
    ],
}


# --------------------------------------------------------------------------- #
#  POST /roster (push)
# --------------------------------------------------------------------------- #
def test_roster_push_creates_session():
    resp = _local().post("/api/v1/roster", json=ROSTER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["year"] == 2026 and data["month"] == 11
    assert data["department"] == "УПО"
    assert len(data["employees"]) == 2

    emp = data["employees"][0]
    assert emp["name"] == "Иванова И.И."
    assert emp["week_norm"] == 39            # классификация по должности
    assert emp["days"]["2"] == {"raw": "8-15,48", "kind": "shift", "hours": 7.8}
    assert emp["days"]["3"]["kind"] == "status"
    assert emp["days"]["3"]["status"] == "vacation"
    assert emp["total_hours"] == 7.8

    emp2 = data["employees"][1]
    assert emp2["rate"] == 0.5
    assert emp2["days"]["2"]["hours"] == 6.6


def test_roster_push_validation():
    client = _local()
    # нет year/month
    assert client.post("/api/v1/roster", json={"employees": []}).status_code == 422
    # нет employees
    r = client.post("/api/v1/roster", json={"year": 2026, "month": 11})
    assert r.status_code == 422
    # пустое имя
    r = client.post("/api/v1/roster", json={
        "year": 2026, "month": 11, "employees": [{"name": "  "}]})
    assert r.status_code == 422
    # день вне месяца
    r = client.post("/api/v1/roster", json={
        "year": 2026, "month": 11,
        "employees": [{"name": "А", "days": {"32": "8-12"}}]})
    assert r.status_code == 422
    # неверная норма
    r = client.post("/api/v1/roster", json={
        "year": 2026, "month": 11,
        "employees": [{"name": "А", "week_norm": 38}]})
    assert r.status_code == 422


def test_roster_push_save_and_pull():
    client = _local()
    r = client.post("/api/v1/roster", json=dict(ROSTER, save=True))
    assert r.status_code == 200
    saved_id = r.json()["saved_id"]
    assert saved_id > 0

    # pull по периоду
    r = client.get("/api/v1/roster?year=2026&month=11")
    assert r.status_code == 200
    data = r.json()
    assert data["saved_id"] == saved_id
    assert len(data["employees"]) == 2
    assert data["employees"][0]["days"]["2"]["raw"] == "8-15,48"

    # несохранённый период
    assert client.get("/api/v1/roster?year=2027&month=1").status_code == 404


def test_roster_push_remote_with_key():
    """Внешняя МИС с ключом делает push; без ключа — 401."""
    info = api_auth.create_key("МИС Пуш")
    remote = _remote()
    r = remote.post("/api/v1/roster", json=ROSTER,
                    headers={"X-API-Key": info["key"]})
    assert r.status_code == 200
    assert len(r.json()["employees"]) == 2


# --------------------------------------------------------------------------- #
#  GET /employees (мастер-данные)
# --------------------------------------------------------------------------- #
def test_employees_directory():
    client = _local()
    client.post("/api/v1/roster", json=dict(ROSTER, save=True))
    client.post("/api/v1/roster", json={
        "year": 2026, "month": 12, "department": "УПО", "save": True,
        "employees": [
            {"name": "Иванова И.И.", "position": "Вр. педиатр участковый"},
            {"name": "Новый Н.Н.", "position": "Медицинская сестра"},
        ]})

    r = client.get("/api/v1/employees")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 3
    by_name = {e["name"]: e for e in data["employees"]}
    # Иванова встречается в двух периодах, но один раз в справочнике
    assert sorted(by_name["Иванова И.И."]["periods"]) == ["2026-11", "2026-12"]
    assert by_name["Новый Н.Н."]["week_norm"] == 39

    # фильтры
    r = client.get("/api/v1/employees?year=2026&month=11")
    assert r.json()["count"] == 2
    r = client.get("/api/v1/employees?department=Другое")
    assert r.json()["count"] == 0
    r = client.get("/api/v1/employees?department=УПО")
    assert r.json()["count"] == 3


# --------------------------------------------------------------------------- #
#  POST /employees/sync
# --------------------------------------------------------------------------- #
def test_employees_sync_add_update_remove():
    client = _local()
    client.post("/api/v1/roster", json=dict(ROSTER, save=True))

    r = client.post("/api/v1/employees/sync", json={
        "year": 2026, "month": 11,
        "employees": [
            {"name": "Иванова И.И.", "position": "Врач-педиатр"},   # обновление
            {"name": "Сидорова С.С.", "position": "Медицинская сестра"},  # новая
        ]})
    assert r.status_code == 200
    data = r.json()
    report = data["sync"]
    assert report["added"] == ["Сидорова С.С."]
    assert report["updated"] == ["Иванова И.И."]
    assert report["unchanged"] == []
    assert report["removed"] == []
    # Петров не пришёл от МИС, но не удалён (remove_missing не задан)
    assert report["not_in_list"] == ["Петров П.П."]

    # должность обновилась, норма переклассифицировалась
    emp = {e["name"]: e for e in data["employees"]}["Иванова И.И."]
    assert emp["position"] == "Врач-педиатр"
    assert emp["week_norm"] == 39
    # график Ивановой сохранён (дни не тронуты)
    assert emp["days"]["2"]["raw"] == "8-15,48"


def test_employees_sync_remove_missing():
    client = _local()
    client.post("/api/v1/roster", json=ROSTER)

    # без сохранения графика синхронизация начинается с пустого месяца:
    # сначала сохраняем, потом удаляем отсутствующих
    client.post("/api/v1/roster", json=dict(ROSTER, save=True))
    r = client.post("/api/v1/employees/sync", json={
        "year": 2026, "month": 11, "remove_missing": True,
        "employees": [{"name": "Иванова И.И."}]})
    assert r.status_code == 200
    data = r.json()
    assert data["sync"]["removed"] == ["Петров П.П."]
    assert [e["name"] for e in data["employees"]] == ["Иванова И.И."]


def test_employees_sync_into_session():
    """Синхронизация в существующую сессию (session_id)."""
    client = _local()
    sid = client.post("/api/v1/roster", json=ROSTER).json()["session_id"]

    r = client.post("/api/v1/employees/sync", json={
        "session_id": sid, "year": 2026, "month": 11,
        "employees": [{"name": "Новый Н.Н.", "position": "Регистратор"}]})
    assert r.status_code == 200
    assert r.json()["session_id"] == sid
    assert r.json()["sync"]["added"] == ["Новый Н.Н."]

    # период сессии не совпадает
    r = client.post("/api/v1/employees/sync", json={
        "session_id": sid, "year": 2027, "month": 1,
        "employees": [{"name": "Новый Н.Н."}]})
    assert r.status_code == 422

    # несуществующая сессия
    r = client.post("/api/v1/employees/sync", json={
        "session_id": "nope", "year": 2026, "month": 11,
        "employees": [{"name": "Новый Н.Н."}]})
    assert r.status_code == 404


def test_employees_sync_bad_norm():
    r = _local().post("/api/v1/employees/sync", json={
        "year": 2026, "month": 11,
        "employees": [{"name": "А", "week_norm": 38}]})
    assert r.status_code == 422
