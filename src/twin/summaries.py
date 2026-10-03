"""`summarize` step: Device resources and CGM / heart-rate summaries into FHIR.

Codes follow the HL7 CGM IG (https://build.fhir.org/ig/HL7/cgm/):
  97507-8 mean glucose, 106793-3 times-in-ranges panel, 104638-2 CV, 97506-0 GMI.
GMI is reported once over the whole sensor window (it is defined over a multi-day
period, not per day). Days below 70 % sensor coverage are skipped.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from twin.config import Settings
from twin.db import connect
from twin.fhir_client import FhirClient, twin_id

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


def run_summarize(cfg: Settings, log=print) -> dict[str, int]:
    fhir = FhirClient()
    fhir.wait_ready()
    counts = {"devices": 0, "observations": 0}
    with connect() as conn:
        patients = [r[0] for r in conn.execute("SELECT patient_id FROM core.patient ORDER BY source_subject_id")]
        for patient_id in patients:
            pid = str(patient_id)
            resources = []
            for device_id, manufacturer, model, kind in conn.execute(
                """
                SELECT d.device_id, m.manufacturer, m.model_name, m.kind
                FROM core.device d JOIN ref.device_model m USING (model_id)
                WHERE d.patient_id = %s ORDER BY d.device_id
                """,
                (patient_id,),
            ):
                resources.append({
                    "resourceType": "Device",
                    "id": twin_id("device", device_id),
                    "meta": {"tag": [TAG]},
                    "identifier": [{"system": "urn:healthcare-digital-twin:device", "value": str(device_id)}],
                    "status": "active",
                    "manufacturer": manufacturer,
                    "deviceName": [{"name": f"{manufacturer} {model}", "type": "manufacturer-name"}],
                    "type": {"text": DEVICE_TYPE[kind]},
                    "patient": {"reference": f"Patient/{pid}"},
                })
            counts["devices"] += len(resources)

            for row in conn.execute(
                """
                SELECT day, device_id, mean_mg_dl, cv_pct, pct_very_low, pct_low, pct_target,
                       pct_high, pct_very_high
                FROM report.cgm_daily WHERE patient_id = %s AND coverage_pct >= %s ORDER BY day
                """,
                (patient_id, MIN_COVERAGE_PCT),
            ).fetchall():
                day, device_id, mean, cv, *pcts = row
                end = day + timedelta(days=1)
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

            window = conn.execute(
                "SELECT device_id, period_start, period_end, gmi FROM report.cgm_window WHERE patient_id = %s",
                (patient_id,),
            ).fetchone()
            if window:
                device_id, start, end, gmi = window
                resources.append(_obs(twin_id(pid, "cgm-gmi"), pid, device_id, "97506-0",
                                      "Glucose management indicator", start, end, valueQuantity=_qty(gmi, "%")))

            for day, device_id, mean_hr in conn.execute(
                """
                SELECT f.day, f.device_id, round(f.mean_hr, 0)
                FROM ts.fitbit_daily f JOIN core.device d USING (device_id)
                WHERE d.patient_id = %s AND f.minutes_worn >= 1440 * %s / 100.0 ORDER BY f.day
                """,
                (patient_id, MIN_COVERAGE_PCT),
            ).fetchall():
                resources.append(_obs(twin_id(pid, "hr-mean", day.date().isoformat()), pid, device_id, "8867-4",
                                      "Heart rate (daily mean)", day, day + timedelta(days=1),
                                      category="vital-signs", valueQuantity=_qty(mean_hr, "/min")))

            fhir.put_all(resources)
            n_obs = sum(r["resourceType"] == "Observation" for r in resources)
            counts["observations"] += n_obs
            log(f"{pid}: {n_obs} observations, {sum(r['resourceType'] == 'Device' for r in resources)} devices")
    return counts
