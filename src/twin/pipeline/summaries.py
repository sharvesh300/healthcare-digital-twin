"""`summarize` step: Device resources and CGM / heart-rate summaries into FHIR.

Codes follow the HL7 CGM IG (https://build.fhir.org/ig/HL7/cgm/):
  97507-8 mean glucose, 106793-3 times-in-ranges panel, 104638-2 CV, 97506-0 GMI.
GMI is reported once over the whole sensor window (it is defined over a multi-day
period, not per day). Days below 70 % sensor coverage are skipped.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from twin.config import Settings
from twin.db import session_scope
from twin.fhir.client import FhirClient, twin_id
from twin.models import Device, Patient
from twin.models import views as v

TAG = {"system": "urn:healthcare-digital-twin:tags", "code": "composite-patient",
       "display": "Composite patient: real CGM/wearable data + synthetic EHR history"}
MIN_COVERAGE_PCT = 70
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
TIR_COMPONENTS = [
    ("pct_very_low", "104642-4", "Time in very low range (<54 mg/dL)"),
    ("pct_low", "104641-6", "Time in low range (54-69 mg/dL)"),
    ("pct_target", "97510-2", "Time in target range (70-180 mg/dL)"),
    ("pct_high", "104640-8", "Time in high range (181-250 mg/dL)"),
    ("pct_very_high", "104639-0", "Time in very high range (>250 mg/dL)"),
]
DEVICE_TYPE = {"cgm": "Continuous glucose monitor", "glucometer": "Blood glucose meter", "wearable": "Activity tracker"}


def _f(value) -> float:
    return float(value) if isinstance(value, Decimal) else value


def _qty(value, unit: str) -> dict:
    return {"value": _f(value), "unit": unit, "system": UCUM, "code": unit}


def _code(code: str, display: str) -> dict:
    return {"coding": [{"system": LOINC, "code": code, "display": display}], "text": display}


def _obs(oid, patient_id, device_id, code, display, start, end, category="laboratory", **value) -> dict:
    return {
        "resourceType": "Observation",
        "id": oid,
        "meta": {"tag": [TAG]},
        "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                  "code": category}]}],
        "code": _code(code, display),
        "subject": {"reference": f"Patient/{patient_id}"},
        "device": {"reference": f"Device/{twin_id('device', device_id)}"},
        "effectivePeriod": {"start": start.isoformat(), "end": end.isoformat()},
        **value,
    }


async def run_summarize(cfg: Settings, log=print) -> dict[str, int]:
    counts = {"devices": 0, "observations": 0}
    async with FhirClient() as fhir:
        await fhir.wait_ready()
        async with session_scope() as s:
            patient_ids = list(await s.scalars(select(Patient.patient_id).order_by(Patient.source_subject_id)))
        for patient_id in patient_ids:
            async with session_scope() as s:
                resources = await _patient_resources(s, patient_id, cfg)
            await fhir.put_all(resources)
            n_obs = sum(r["resourceType"] == "Observation" for r in resources)
            n_dev = sum(r["resourceType"] == "Device" for r in resources)
            counts["observations"] += n_obs
            counts["devices"] += n_dev
            log(f"{patient_id}: {n_obs} observations, {n_dev} devices")
    return counts


async def _patient_resources(s, patient_id, cfg: Settings) -> list[dict]:
    pid = str(patient_id)
    tz = cfg.tz
    resources = []
    devices = await s.scalars(select(Device).where(Device.patient_id == patient_id).order_by(Device.device_id))
    for device in devices:
        m = device.model
        resources.append({
            "resourceType": "Device",
            "id": twin_id("device", device.device_id),
            "meta": {"tag": [TAG]},
            "identifier": [{"system": "urn:healthcare-digital-twin:device", "value": str(device.device_id)}],
            "status": "active",
            "manufacturer": m.manufacturer,
            "deviceName": [{"name": f"{m.manufacturer} {m.model_name}", "type": "manufacturer-name"}],
            "type": {"text": DEVICE_TYPE[m.kind]},
            "patient": {"reference": f"Patient/{pid}"},
        })

    c = v.cgm_daily.c
    daily = await s.execute(
        select(c.day, c.device_id, c.mean_mg_dl, c.cv_pct, c.pct_very_low, c.pct_low, c.pct_target,
               c.pct_high, c.pct_very_high)
        .where(c.patient_id == patient_id, c.coverage_pct >= MIN_COVERAGE_PCT)
        .order_by(c.day)
    )
    for day, device_id, mean, cv, *pcts in daily:
        day = day.astimezone(tz)
        end = day + timedelta(days=1)  # wall-clock day, correct across DST changes
        key = day.date().isoformat()
        resources.append(_obs(twin_id(pid, "cgm-mean", key), pid, device_id, "97507-8",
                              "Average glucose in interstitial fluid", day, end,
                              valueQuantity=_qty(mean, "mg/dL")))
        resources.append(_obs(twin_id(pid, "cgm-cv", key), pid, device_id, "104638-2",
                              "Glucose coefficient of variation", day, end, valueQuantity=_qty(cv, "%")))
        resources.append(_obs(
            twin_id(pid, "cgm-tir", key), pid, device_id, "106793-3", "Glucose times in ranges", day, end,
            component=[{"code": _code(code, display), "valueQuantity": _qty(pct, "%")}
                       for (_, code, display), pct in zip(TIR_COMPONENTS, pcts)],
        ))

    w = v.cgm_window.c
    window = (await s.execute(
        select(w.device_id, w.period_start, w.period_end, w.gmi).where(w.patient_id == patient_id)
    )).first()
    if window:
        device_id, start, end, gmi = window
        resources.append(_obs(twin_id(pid, "cgm-gmi"), pid, device_id, "97506-0", "Glucose management indicator",
                              start.astimezone(tz), end.astimezone(tz), valueQuantity=_qty(gmi, "%")))

    f = v.fitbit_daily.c
    heart = await s.execute(
        select(f.day, f.device_id, f.mean_hr)
        .join(Device, Device.device_id == f.device_id)
        .where(Device.patient_id == patient_id, f.minutes_worn >= 1440 * MIN_COVERAGE_PCT / 100)
        .order_by(f.day)
    )
    for day, device_id, mean_hr in heart:
        day = day.astimezone(tz)
        resources.append(_obs(twin_id(pid, "hr-mean", day.date().isoformat()), pid, device_id, "8867-4",
                              "Heart rate (daily mean)", day, day + timedelta(days=1),
                              category="vital-signs", valueQuantity=_qty(round(mean_hr), "/min")))
    return resources
