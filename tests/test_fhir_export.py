# -*- coding: utf-8 -*-
"""Тесты Фазы 3: экспорт графика в HL7 FHIR R4 (Bundle).

Проверяется структура Bundle: Practitioner/Schedule/Slot, форматы instant,
отражение смен и неявок, поведение при неразобранных ячейках.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import app.main as main
from app.core import api_auth, config
from fastapi.testclient import TestClient

LOCAL = ("127.0.0.1", 50000)


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


def _session_with_roster(client):
    resp = client.post("/api/v1/roster", json={
        "year": 2026, "month": 11, "department": "УПО",
        "employees": [
            {"name": "Иванова И.И.", "position": "Вр. педиатр участковый",
             "days": {
                 "2": "8-15,48",            # смена
                 "3": "О",                  # отпуск
                 "4": "В",                  # выходной — слота не даёт
                 "5": "8-12 12.30-16.30",   # разрывная смена: 2 слота
             }},
            {"name": "Петров П.П.", "position": "Санитарка",
             "days": {"2": "8-14,36", "6": "бред"}},
        ]})
    assert resp.status_code == 200
    return resp.json()["session_id"]


def _bundle(client, sid, tz=None):
    url = "/api/v1/export/fhir/%s" % sid
    if tz:
        url += "?tz=" + tz
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/fhir+json")
    return resp.json()


def _resources(bundle, rtype):
    return [e["resource"] for e in bundle["entry"]
            if e["resource"]["resourceType"] == rtype]


def test_bundle_structure():
    client = TestClient(main.app, client=LOCAL)
    sid = _session_with_roster(client)
    bundle = _bundle(client, sid)

    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "collection"
    assert bundle["id"] == "med-roster-2026-11"
    assert len(_resources(bundle, "Practitioner")) == 2
    assert len(_resources(bundle, "Schedule")) == 2

    practitioner = _resources(bundle, "Practitioner")[0]
    assert practitioner["name"][0]["text"] == "Иванова И.И."
    assert practitioner["identifier"][0]["value"] == "Иванова И.И."

    schedule = _resources(bundle, "Schedule")[0]
    assert schedule["actor"][0]["reference"] == "Practitioner/practitioner-1"
    assert schedule["actor"][0]["display"] == "Иванова И.И."
    assert schedule["comment"] == "Вр. педиатр участковый"


def test_slots_from_shifts():
    client = TestClient(main.app, client=LOCAL)
    sid = _session_with_roster(client)
    bundle = _bundle(client, sid)
    slots = _resources(bundle, "Slot")

    # Иванова: 8-15,48 (1) + О (1) + разрывная смена (2) = 4 слота
    # Петров: 8-14,36 (1) = 1 слот; «бред» — invalid, слота нет
    assert len(slots) == 5

    first = [s for s in slots if s["id"] == "slot-1-1"][0]
    assert first["schedule"]["reference"] == "Schedule/schedule-1"
    assert first["start"] == "2026-11-02T08:00:00+03:00"
    assert first["end"] == "2026-11-02T15:48:00+03:00"
    assert first["status"] == "busy"
    assert first["comment"] == "8-15,48"

    # разрывная смена — два последовательных слота
    split = sorted([s for s in slots
                    if s["start"].startswith("2026-11-05")],
                   key=lambda s: s["start"])
    assert len(split) == 2
    assert split[0]["end"] == "2026-11-05T12:00:00+03:00"
    assert split[1]["start"] == "2026-11-05T12:30:00+03:00"


def test_absence_and_day_off():
    client = TestClient(main.app, client=LOCAL)
    sid = _session_with_roster(client)
    bundle = _bundle(client, sid)
    slots = _resources(bundle, "Slot")

    vacation = [s for s in slots if s["status"] == "busy-unavailable"]
    assert len(vacation) == 1
    assert vacation[0]["comment"] == "Отпуск"
    assert vacation[0]["start"].startswith("2026-11-03T00:00:00")

    # выходной (В) не создаёт слота: у Ивановой нет слота на 4-е число
    assert not [s for s in slots if s["start"].startswith("2026-11-04")]


def test_invalid_cell_operation_outcome():
    client = TestClient(main.app, client=LOCAL)
    sid = _session_with_roster(client)
    bundle = _bundle(client, sid)

    outcomes = _resources(bundle, "OperationOutcome")
    assert len(outcomes) == 1
    issue = outcomes[0]["issue"][0]
    assert issue["severity"] == "warning"
    assert "1" in issue["diagnostics"]


def test_tz_parameter():
    client = TestClient(main.app, client=LOCAL)
    sid = _session_with_roster(client)

    # «+» в query декодируется в пробел — нормализуется в «+04:00»
    bundle = _bundle(client, sid, tz="+04:00")
    slot = _resources(bundle, "Slot")[0]
    assert slot["start"].endswith("+04:00")

    # явное кодирование %2B тоже работает
    bundle = _bundle(client, sid, tz="%2B04%3A00")
    slot = _resources(bundle, "Slot")[0]
    assert slot["start"].endswith("+04:00")

    # отрицательное смещение
    bundle = _bundle(client, sid, tz="-05:00")
    slot = _resources(bundle, "Slot")[0]
    assert slot["start"].endswith("-05:00")


def test_tz_validation():
    client = TestClient(main.app, client=LOCAL)
    sid = _session_with_roster(client)
    r = client.get("/api/v1/export/fhir/%s?tz=абракадабра" % sid)
    assert r.status_code == 422
    r = client.get("/api/v1/export/fhir/%s?tz=25:00" % sid)
    assert r.status_code == 422


def test_fhir_requires_session():
    client = TestClient(main.app, client=LOCAL)
    assert client.get("/api/v1/export/fhir/nope").status_code == 404
