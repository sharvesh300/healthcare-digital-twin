"""Assemble the patient record from a patient's rows (twin.record.store.RecordData).

Pure: no I/O, so every rule is tested with plain dicts. Four summary shapes are shared by
the overview, the lists and the detail pages:

    MedicationSummary  one per ingredient (rxcui): current product and dosage, episodes
    ConditionSummary   one per concept: active, episodes, latest episode
    MeasureSummary     one per test or vital: latest and previous result, flag, sparkline
    VisitSummary       one per encounter: class, type, reason, what was recorded at it

A detail adds every occurrence (each prescription, episode, result) and `related` entries,
always in the same summary shapes, so a client renders a link to anything the same way.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from itertools import pairwise
from statistics import fmean
from typing import Any

from twin.clinical.measures import COMPONENT_RANGES, GROUP_MEASURES, MEASURES, PANELS, Measure, flag, measure_for
from twin.record.store import RecordData

SINGLE_DAY = timedelta(days=1)
OUT_OF_RANGE = ("high", "low")
SPARK_POINTS = 12
HEADLINE = ("hba1c", "blood_pressure", "bmi", "ldl", "egfr_reported")
COHORT = {"cgmacros": "CGMacros", "bigideas": "BIG IDEAs"}
_ORDER = {key: i for i, key in enumerate(MEASURES)}


def _newest_first(items: list[dict], key: str) -> list[dict]:
    return sorted(items, key=lambda x: x[key], reverse=True)


# ── visits ───────────────────────────────────────────────────────────


def visit_brief(v: dict | None) -> dict | None:
    if v is None:
        return None
    return {"encounter_id": v["encounter_id"], "class": v["encounter_class"], "type": v["type"],
            "start": v["started_at"]}


def _visits(data: RecordData) -> dict[str, dict]:
    return {v["encounter_id"]: v for v in data.visits}


def _window(v: dict) -> tuple[datetime, datetime]:
    end = v["ended_at"] or v["started_at"]
    return v["started_at"], max(end, v["started_at"] + timedelta(minutes=1))


def has_records(v: dict) -> bool:
    """Whether anything (a test, a diagnosis, a medication) was recorded at a visit summary."""
    return any(v["counts"].values())


def visit_summaries(data: RecordData) -> list[dict]:
    """Every visit, newest first, with what was recorded at it."""
    tests: dict[str, set[str]] = defaultdict(set)
    for r in data.results:
        if r["encounter_id"]:
            tests[r["encounter_id"]].add(measure_for(r["analyte"]).key)
    diagnoses = defaultdict(int)
    for c in data.conditions:
        if c["encounter_id"]:
            diagnoses[c["encounter_id"]] += 1
    medications = defaultdict(int)
    for m in data.medications:
        if m["encounter_id"]:
            medications[m["encounter_id"]] += 1
    out = []
    for v in data.visits:
        eid = v["encounter_id"]
        hours = (v["ended_at"] - v["started_at"]).total_seconds() / 3600 if v["ended_at"] else None
        out.append({**visit_brief(v), "reason": v["reason"], "end": v["ended_at"],
                    "duration_h": round(hours, 1) if hours is not None else None,
                    "counts": {"tests": len(tests[eid]), "diagnoses": diagnoses[eid], "medications": medications[eid]},
                    "source": v["source"], "is_synthetic": v["is_synthetic"]})
        out[-1]["has_records"] = has_records(out[-1])
    return _newest_first(out, "start")


def visits_page(data: RecordData, year: int | None = None, cls: str | None = None, limit: int = 20,
                cursor: str | None = None) -> dict:
    """Visits newest first, filtered by year and class, `limit` at a time. The cursor is
    opaque to clients (an offset today)."""
    every = visit_summaries(data)
    items = [v for v in every if (year is None or v["start"].year == year) and (cls is None or v["class"] == cls)]
    offset = int(cursor) if cursor and cursor.isdigit() else 0
    page = items[offset:offset + limit]
    # each facet counts what choosing it would show alongside the other filter, so a client
    # can disable a choice that leads to an empty list
    years = defaultdict(int)
    classes = defaultdict(int)
    for v in every:
        if cls is None or v["class"] == cls:
            years[v["start"].year] += 1
        if year is None or v["start"].year == year:
            classes[v["class"]] += 1
    return {"total": len(items), "items": page,
            "next_cursor": str(offset + limit) if offset + limit < len(items) else None,
            "years": [{"year": y, "count": n} for y, n in sorted(years.items(), reverse=True)],
            "classes": [{"class": c, "count": n} for c, n in sorted(classes.items(), key=lambda x: -x[1])]}


# ── medications ──────────────────────────────────────────────────────

_FREQUENCY = {1: "once daily", 2: "twice daily", 3: "three times daily", 4: "four times daily"}


def _num(x: float) -> str:
    return f"{x:g}"


def dosage(r: dict) -> dict:
    """Dose and frequency, plus a reading such as "5 mg · once daily" (None when the
    source recorded neither: the product then says the strength)."""
    parts = []
    if r["dose_value"] is not None:
        parts.append(f"{_num(r['dose_value'])} {r['dose_unit'] or ''}".strip())
    t = r["times_per_day"]
    if r["as_needed"]:
        parts.append("as needed")
    elif t:
        if abs(t - round(t)) < 0.01 and round(t) in _FREQUENCY:
            parts.append(_FREQUENCY[round(t)])
        elif t > 1:
            parts.append(f"{_num(round(t, 1))} times daily")
        else:
            days = round(1 / t)
            parts.append("weekly" if days == 7 else "monthly" if days in (28, 30, 31) else f"every {days} days")
    return {"dose_value": r["dose_value"], "dose_unit": r["dose_unit"], "times_per_day": t,
            "as_needed": r["as_needed"], "text": " · ".join(parts) or None}


def _single_day(r: dict) -> bool:
    """Given during one visit (an anaesthetic, a one-off injection), not a standing regimen."""
    return r["ended_at"] is not None and r["ended_at"] - r["started_at"] < SINGLE_DAY


def medication_summaries(rows: list[dict]) -> list[dict]:
    """One per ingredient: active ones first, glucose-lowering first, then newest."""
    by_rxcui: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_rxcui[r["rxcui"]].append(r)
    out = []
    for rxcui, episodes in by_rxcui.items():
        episodes.sort(key=lambda r: r["started_at"])
        current = next((e for e in reversed(episodes) if e["active"]), episodes[-1])
        out.append({
            "rxcui": rxcui, "medication": current["medication"], "product": current["product"],
            "drug_class": current["drug_class"], "drug_class_display": current["drug_class_display"],
            "glucose_lowering": current["glucose_lowering"], "active": any(e["active"] for e in episodes),
            "dosage": dosage(current), "started_at": current["started_at"], "ended_at": current["ended_at"],
            "first_started_at": episodes[0]["started_at"], "episodes": len(episodes),
            "single_day": all(_single_day(e) for e in episodes), "encounter_id": current["encounter_id"],
            "source": current["source"], "is_synthetic": all(e["is_synthetic"] for e in episodes),
        })
    out = _newest_first(out, "started_at")
    return sorted(out, key=lambda m: (not m["active"], not m["glucose_lowering"]))


def medications_list(data: RecordData, active: bool | None = None, glucose_lowering: bool | None = None,
                     drug_class: str | None = None) -> dict:
    every = medication_summaries(data.medications)
    items = [m for m in every if (active is None or m["active"] == active)
             and (glucose_lowering is None or m["glucose_lowering"] == glucose_lowering)
             and (drug_class is None or m["drug_class"] == drug_class)]
    return {"total": len(items), "active": sum(m["active"] for m in items),
            "items": [m for m in items if not m["single_day"]],
            "single_day": _newest_first([m for m in items if m["single_day"]], "started_at")}


def _medication_label(r: dict) -> str:
    return " · ".join(x for x in (r["product"] or r["medication"], dosage(r)["text"]) if x)


def medication_detail(data: RecordData, rxcui: int) -> dict | None:
    episodes = sorted((r for r in data.medications if r["rxcui"] == rxcui), key=lambda r: r["started_at"])
    if not episodes:
        return None
    visits = _visits(data)
    summary = medication_summaries(episodes)[0]
    changes = [{"at": b["started_at"], "from": _medication_label(a), "to": _medication_label(b)}
               for a, b in pairwise(episodes)
               if (a["product_rxcui"], a["dose_value"], a["times_per_day"], a["as_needed"])
               != (b["product_rxcui"], b["dose_value"], b["times_per_day"], b["as_needed"])]
    prescribed_at = {e["encounter_id"] for e in episodes if e["encounter_id"]}
    measures = measure_summaries(data)
    return {
        "medication": summary,
        "episodes": [{"regimen_id": e["regimen_id"], "product": e["product"], "product_rxcui": e["product_rxcui"],
                      "dosage": dosage(e), "started_at": e["started_at"], "ended_at": e["ended_at"],
                      "active": e["active"], "single_day": _single_day(e), "visit": visit_brief(visits.get(e["encounter_id"])),
                      "source": e["source"], "is_synthetic": e["is_synthetic"]} for e in episodes],
        "dose_changes": changes,
        "related": {
            "diagnoses": condition_summaries([c for c in data.conditions if c["encounter_id"] in prescribed_at]),
            "measures": _sorted([s for key, s in measures.items()
                                 if key in MEASURES and summary["drug_class"] in MEASURES[key].drug_classes]),
        },
    }


# ── conditions ───────────────────────────────────────────────────────


def condition_summaries(rows: list[dict]) -> list[dict]:
    """One per concept: active ones first, then by their latest change."""
    by_concept: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_concept[r["concept_id"]].append(r)
    out = []
    for concept_id, episodes in by_concept.items():
        episodes.sort(key=lambda r: r["onset_at"])
        latest = episodes[-1]
        out.append({
            "concept_id": concept_id, "system": latest["system"], "code": latest["code"],
            "display": latest["display"], "kind": latest["kind"], "group": latest["condition_group"],
            "group_display": latest["condition_group_display"], "active": any(e["active"] for e in episodes),
            "episodes": len(episodes), "first_onset": episodes[0]["onset_at"],
            "current": {"onset_at": latest["onset_at"], "abated_at": latest["abated_at"], "active": latest["active"]},
            "last_change": max(latest["onset_at"], latest["abated_at"] or latest["onset_at"]),
            "source": latest["source"], "is_synthetic": all(e["is_synthetic"] for e in episodes),
        })
    return sorted(_newest_first(out, "last_change"), key=lambda c: not c["active"])


def conditions_list(data: RecordData, active: bool | None = None, kind: str | None = None,
                    group: str | None = None) -> dict:
    items = [c for c in condition_summaries(data.conditions)
             if (active is None or c["active"] == active) and (kind is None or c["kind"] == kind)
             and (group is None or c["group"] == group)]
    return {"total": len(items), "active": sum(c["active"] for c in items), "items": items}


def condition_detail(data: RecordData, concept_id: int) -> dict | None:
    episodes = sorted((c for c in data.conditions if c["concept_id"] == concept_id), key=lambda c: c["onset_at"])
    if not episodes:
        return None
    visits = _visits(data)
    summary = condition_summaries(episodes)[0]
    seen_at = {e["encounter_id"] for e in episodes if e["encounter_id"]}
    measures = measure_summaries(data)
    return {
        "condition": summary,
        "episodes": [{"onset_at": e["onset_at"], "abated_at": e["abated_at"], "active": e["active"],
                      "duration_days": (e["abated_at"] - e["onset_at"]).days if e["abated_at"] else None,
                      "visit": visit_brief(visits.get(e["encounter_id"])), "source": e["source"],
                      "is_synthetic": e["is_synthetic"]} for e in episodes],
        "related": {
            "medications": medication_summaries([m for m in data.medications if m["encounter_id"] in seen_at]),
            "measures": [measures[k] for k in GROUP_MEASURES.get(summary["group"] or "", ()) if k in measures],
        },
    }


# ── tests and vitals ─────────────────────────────────────────────────


def _results(data: RecordData) -> dict[str, tuple[Measure, list[dict]]]:
    """Results grouped by measure, oldest first; one result per measure and time, holding
    every component (SBP and DBP together). Real values win over synthetic ones at the
    same time (rows arrive real first)."""
    sex = data.patient.get("sex")
    grouped: dict[str, tuple[Measure, dict[datetime, dict]]] = {}
    for r in data.results:
        m = measure_for(r["analyte"], r["loinc_display"])
        _, at = grouped.setdefault(m.key, (m, {}))
        res = at.setdefault(r["effective_at"], {
            "at": r["effective_at"], "values": {}, "text": None, "unit": r["ucum_unit"],
            "encounter_id": r["encounter_id"], "source": r["source"], "is_synthetic": r["is_synthetic"]})
        if r["value_num"] is not None:
            res["values"].setdefault(r["analyte"], r["value_num"])
        elif r["value_text"] and res["text"] is None:
            res["text"] = r["value_text"]
    out = {}
    for key, (m, at) in grouped.items():
        results = sorted(at.values(), key=lambda x: x["at"])
        for res in results:
            res["flag"] = flag(m, res["values"], sex)
        out[key] = (m, results)
    return out


def _brief(res: dict | None) -> dict | None:
    if res is None:
        return None
    return {k: res[k] for k in ("at", "values", "text", "flag", "encounter_id", "source", "is_synthetic")}


def _summary(m: Measure, results: list[dict], sex: str | None) -> dict:
    multi = len(m.analytes) > 1
    primary = m.analytes[0]
    return {
        "measure": m.key, "display": m.display, "panel": m.panel, "panel_display": PANELS[m.panel],
        "unit": m.unit or results[-1]["unit"], "digits": m.digits, "analytes": list(m.analytes),
        "ranges": {a: (COMPONENT_RANGES.get(a) if multi else m.range_for(sex)) for a in m.analytes},
        "count": len(results), "out_of_range": sum(r["flag"] in OUT_OF_RANGE for r in results),
        "latest": _brief(results[-1]), "previous": _brief(results[-2]) if len(results) > 1 else None,
        "spark": [[r["at"], r["values"][primary]] for r in results if primary in r["values"]][-SPARK_POINTS:],
        "is_synthetic": all(r["is_synthetic"] for r in results),
    }


def measure_summaries(data: RecordData) -> dict[str, dict]:
    sex = data.patient.get("sex")
    return {key: _summary(m, results, sex) for key, (m, results) in _results(data).items()}


def _sorted(summaries: list[dict]) -> list[dict]:
    return sorted(summaries, key=lambda s: (_ORDER.get(s["measure"], len(_ORDER)), s["display"]))


def panels(summaries: list[dict]) -> list[dict]:
    by_panel = defaultdict(list)
    for s in summaries:
        by_panel[s["panel"]].append(s)
    return [{"panel": p, "display": PANELS[p], "measures": _sorted(by_panel[p])} for p in PANELS if by_panel[p]]


def tests_list(data: RecordData, panel: str | None = None, out_of_range: bool = False) -> dict:
    items = [s for s in measure_summaries(data).values()
             if (panel is None or s["panel"] == panel) and (not out_of_range or s["latest"]["flag"] in OUT_OF_RANGE)]
    return {"total": len(items), "panels": panels(items)}


def measure_detail(data: RecordData, key: str) -> dict | None:
    grouped = _results(data)
    if key not in grouped:
        return None
    m, results = grouped[key]
    summaries = {k: _summary(mm, rr, data.patient.get("sex")) for k, (mm, rr) in grouped.items()}
    visits = _visits(data)
    stats = {a: {"min": min(vals), "max": max(vals), "mean": round(fmean(vals), 2)}
             for a in m.analytes if (vals := [r["values"][a] for r in results if a in r["values"]])}
    groups = {g for g, keys in GROUP_MEASURES.items() if key in keys}
    return {
        "measure": summaries[key],
        "stats": {"count": len(results), "first_at": results[0]["at"], "latest_at": results[-1]["at"],
                  "out_of_range": summaries[key]["out_of_range"], "by_analyte": stats},
        "results": [{**_brief(r), "visit": visit_brief(visits.get(r["encounter_id"]))} for r in results],
        "related": {
            "panel": _sorted([s for k, s in summaries.items() if s["panel"] == m.panel and k != key]),
            "medications": [s for s in medication_summaries(data.medications) if s["drug_class"] in m.drug_classes],
            "diagnoses": [c for c in condition_summaries(data.conditions) if c["group"] in groups],
        },
    }


# ── one visit ────────────────────────────────────────────────────────


def visit_detail(data: RecordData, encounter_id: str) -> dict | None:
    summaries = visit_summaries(data)
    index = next((i for i, v in enumerate(summaries) if v["encounter_id"] == encounter_id), None)
    if index is None:
        return None
    visit = summaries[index]
    start, end = _window(_visits(data)[encounter_id])
    tests = []
    for _, (m, results) in _results(data).items():
        for r in results:
            if r["encounter_id"] == encounter_id:
                tests.append({"measure": m.key, "display": m.display, "panel": m.panel, "unit": m.unit or r["unit"],
                              "digits": m.digits, "analytes": list(m.analytes), **_brief(r)})
    by_panel = defaultdict(list)
    for t in tests:
        by_panel[t["panel"]].append(t)
    conditions = data.conditions
    started = [m for m in data.medications if m["encounter_id"] == encounter_id]
    return {
        "visit": visit,
        "tests": [{"panel": p, "display": PANELS[p], "items": sorted(by_panel[p], key=lambda t: _ORDER.get(t["measure"], 999))}
                  for p in PANELS if by_panel[p]],
        "diagnoses": {
            "recorded": condition_summaries([c for c in conditions if c["encounter_id"] == encounter_id]),
            "resolved": condition_summaries([c for c in conditions if c["encounter_id"] != encounter_id
                                             and c["abated_at"] and start <= c["abated_at"] <= end]),
        },
        "medications": {
            "started": medication_summaries(started),
            "stopped": medication_summaries([m for m in data.medications if m["encounter_id"] != encounter_id
                                             and m["ended_at"] and start <= m["ended_at"] <= end]),
        },
        # the neighbouring visits that have something recorded (summaries are newest first);
        # visits with nothing recorded are skipped, so stepping never lands on an empty page
        "previous": next((v for v in summaries[index + 1:] if v["has_records"]), None),
        "next": next((v for v in reversed(summaries[:index]) if v["has_records"]), None),
    }


# ── overview ─────────────────────────────────────────────────────────


def _provenance(patient: dict) -> dict:
    composite = "composite-patient" in (patient.get("tags") or [])
    cohort = COHORT.get(patient["source"], patient["source"])
    note = (f"Composite twin: CGM and wearable data and the baseline labs are real ({cohort}); the EHR history "
            "(visits, diagnoses, medications and most tests) is synthetic (Synthea)."
            if composite else "Single-source data.")
    return {"cohort": patient["source"], "composite": composite, "note": note}


def _derived(b: dict | None) -> dict:
    if not b:
        return {}
    syn = set(b.get("synthetic_analytes") or [])
    items = {
        "egfr": (b["egfr"], b["egfr_is_synthetic"], "eGFR (CKD-EPI 2021)", "mL/min/1.73 m²"),
        "ldl": (b["ldl"], b["ldl_is_synthetic"], "LDL (measured or Friedewald)", "mg/dL"),
        "homa_ir": (b["homa_ir"], b["homa_ir_is_synthetic"], "HOMA-IR", None),
        "non_hdl": (b["non_hdl"], bool(syn & {"cholesterol_total", "hdl"}), "Non-HDL cholesterol", "mg/dL"),
        "tc_hdl_ratio": (b["tc_hdl_ratio"], bool(syn & {"cholesterol_total", "hdl"}), "Total/HDL ratio", None),
    }
    return {k: {"value": v, "is_synthetic": s, "display": d, "unit": u} for k, (v, s, d, u) in items.items()
            if v is not None}


def _recent(items: list[dict], n: int) -> list[dict]:
    """The active items, then the `n` most recently ended."""
    return [i for i in items if i["active"]] + [i for i in items if not i["active"]][:n]


def overview(data: RecordData) -> dict[str, Any]:
    meds = medication_summaries(data.medications)
    standing = [m for m in meds if not m["single_day"]]
    conditions = condition_summaries(data.conditions)
    measures = measure_summaries(data)
    visits = visit_summaries(data)
    by_kind = {k: [c for c in conditions if c["kind"] == k] for k in ("diagnosis", "finding")}
    return {
        "patient": data.patient,
        "provenance": _provenance(data.patient),
        "summary": {
            "medications_active": sum(m["active"] for m in standing),
            "glucose_lowering_active": sum(m["active"] and m["glucose_lowering"] for m in standing),
            "diagnoses_active": sum(c["active"] for c in by_kind["diagnosis"]),
            "last_visit": visits[0] if visits else None,
            "headline": [measures[k] for k in HEADLINE if k in measures],
        },
        "medications": {"total": len(meds), "active": sum(m["active"] for m in standing),
                        "single_day": sum(m["single_day"] for m in meds), "items": _recent(standing, 5)},
        "conditions": {k: {"total": len(v), "active": sum(c["active"] for c in v), "items": _recent(v, 5)}
                       for k, v in (("diagnoses", by_kind["diagnosis"]), ("findings", by_kind["finding"]))},
        "tests": {"total": len(measures), "out_of_range": sum(s["latest"]["flag"] in OUT_OF_RANGE for s in measures.values()),
                  "panels": panels(list(measures.values()))},
        "visits": {"total": len(visits), "with_records": sum(v["has_records"] for v in visits), "recent": visits[:8]},
        "derived": _derived(data.baseline),
        "cgm": data.cgm,
    }
