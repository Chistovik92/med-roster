# -*- coding: utf-8 -*-
"""Экспорт графика в формате HL7 FHIR R4 (Bundle).

График месяца представляется коллекцией ресурсов:

* ``Practitioner``  — сотрудник (identifier = Ф.И.О. из графика);
* ``Schedule``      — расписание сотрудника на месяц (actor → Practitioner);
* ``Slot``          — один интервал работы или неявки в конкретный день:
  * смена («8-15,48», в т.ч. разрывная «8-12 12.30-16.30») →
    ``status=busy`` с start/end;
  * отпуск/больничный/учёба (О/ОТ/Б/У/ПК) → ``status=busy-unavailable``
    с комментарием;
  * выходной (В) и явка (Я) слотами не отражаются (свободное время);
* ``OperationOutcome`` — предупреждение о неразобранных ячейках (severity=warning).

Время указывается в местном часовом поясе (параметр ``tz``, по умолчанию
``+03:00`` — московское время; для Саратова передавайте ``+04:00``).

Ссылки: HL7 FHIR R4 — https://hl7.org/fhir/R4/
"""
from __future__ import annotations

import datetime as _dt
from typing import Dict, List

from app.core.constants import STATUS_CODES
from app.services.xls_importer import ImportResult

# Русские подписи типов неявок (для комментария к слоту).
_STATUS_LABELS = {
    "day_off": "Выходной",
    "vacation": "Отпуск",
    "sick": "Больничный",
    "study": "Учёба",
    "present": "Явка",
}

# Коды неявок, которые отражаются слотом busy-unavailable (В и Я — не отражаются).
_ABSENCE_SLOT_TYPES = ("vacation", "sick", "study")


def _instant(year: int, month: int, day: int, minutes: int, tz: str) -> str:
    """FHIR-instant: дата + время (ЧЧ:ММ:СС) + смещение часового пояса.

    ``minutes`` может превышать сутки (1440): слот неявки «весь день»
    заканчивается в 24:00, а время ``24:00`` в FHIR недопустимо — поэтому
    лишние минуты переносятся на следующие сутки (00:00 следующего дня).
    ``datetime`` корректно перекатывает и месяц, и год (31-е число).
    """
    base = _dt.datetime(year, month, day) + _dt.timedelta(minutes=minutes)
    return "%04d-%02d-%02dT%02d:%02d:00%s" % (
        base.year, base.month, base.day, base.hour, base.minute, tz)


def _slug_id(prefix: str, num: int) -> str:
    return "%s-%d" % (prefix, num)


def export_fhir_bundle(res: ImportResult, tz: str = "+03:00") -> Dict:
    """Собрать FHIR R4 Bundle (type=collection) по графику месяца."""
    entries: List[Dict] = []
    invalid_cells = 0

    for i, row in enumerate(res.rows, start=1):
        practitioner_id = _slug_id("practitioner", i)
        schedule_id = _slug_id("schedule", i)

        entries.append({
            "fullUrl": "urn:uuid:med-roster:" + practitioner_id,
            "resource": {
                "resourceType": "Practitioner",
                "id": practitioner_id,
                "identifier": [{
                    "system": "urn:med-roster:employee",
                    "value": row.name,
                }],
                "name": [{"text": row.name}],
                "active": True,
            },
        })
        entries.append({
            "fullUrl": "urn:uuid:med-roster:" + schedule_id,
            "resource": {
                "resourceType": "Schedule",
                "id": schedule_id,
                "identifier": [{
                    "system": "urn:med-roster:schedule",
                    "value": "%d-%02d/%s" % (res.year, res.month, row.name),
                }],
                "actor": [{
                    "reference": "Practitioner/" + practitioner_id,
                    "display": row.name,
                }],
                "comment": (row.position or "").strip(),
            },
        })

        slot_num = 0
        for day in sorted(row.raw_cells.keys()):
            pc = row.parsed.get(day)
            if pc is None:
                continue
            if pc.kind == "shift":
                for iv in pc.intervals:
                    slot_num += 1
                    slot_id = _slug_id("slot-%d" % i, slot_num)
                    entries.append({
                        "fullUrl": "urn:uuid:med-roster:" + slot_id,
                        "resource": {
                            "resourceType": "Slot",
                            "id": slot_id,
                            "schedule": {"reference": "Schedule/" + schedule_id},
                            "start": _instant(res.year, res.month, day,
                                              iv.start, tz),
                            "end": _instant(res.year, res.month, day,
                                            iv.end, tz),
                            "status": "busy",
                            "comment": pc.raw,
                        },
                    })
            elif pc.kind == "status":
                label = _STATUS_LABELS.get(pc.status or "", pc.status or "")
                if (pc.status or "") not in _ABSENCE_SLOT_TYPES:
                    continue  # В/Я не создают слотов
                slot_num += 1
                slot_id = _slug_id("slot-%d" % i, slot_num)
                entries.append({
                    "fullUrl": "urn:uuid:med-roster:" + slot_id,
                    "resource": {
                        "resourceType": "Slot",
                        "id": slot_id,
                        "schedule": {"reference": "Schedule/" + schedule_id},
                        "start": _instant(res.year, res.month, day, 0, tz),
                        "end": _instant(res.year, res.month, day, 24 * 60, tz),
                        "status": "busy-unavailable",
                        "comment": label,
                    },
                })
            elif pc.kind == "invalid":
                invalid_cells += 1

    if invalid_cells:
        entries.append({
            "fullUrl": "urn:uuid:med-roster:outcome",
            "resource": {
                "resourceType": "OperationOutcome",
                "id": "outcome",
                "issue": [{
                    "severity": "warning",
                    "code": "processing",
                    "diagnostics": "Ячеек не удалось разобрать: %d — они "
                                   "экспортированы как пустые" % invalid_cells,
                }],
            },
        })

    return {
        "resourceType": "Bundle",
        "id": "med-roster-%d-%02d" % (res.year, res.month),
        "type": "collection",
        "timestamp": "%04d-%02d-%02dT00:00:00%s" % (
            res.year, res.month, res.day_count, tz),
        "entry": entries,
    }
