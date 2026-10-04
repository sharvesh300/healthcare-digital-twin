"""`fuse-cgm` step: fuse each patient's two CGMs into ts.glucose_fused.

Per patient: estimate the lag between the CGMs, decide sensor lag vs clock offset
(clock offsets are resolved with the meal log, against the cohort's typical post-meal
time-to-peak), calibrate the secondary CGM onto the reference CGM, fuse on a 5-min
grid, store the parameters in core.cgm_calibration. Writes a validation report
comparing each stream with lab HbA1c (via GMI) and with fingersticks.
"""

from __future__ import annotations

import csv
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from twin.analytics import cgm_fusion as cf
from twin.config import Settings
from twin.db import copy_records, engine, session_scope
from twin.models import (
    CgmCalibration,
    DataSource,
    Device,
    DeviceKind,
    DeviceModel,
    GlucoseFused,
    GlucoseReading,
    Patient,
)
from twin.models import views as v
from twin.sources import cgmacros

MEAL_MIN_CARBS_G = 20  # meals big enough to produce a clear glucose peak
FINGERSTICK_TOLERANCE = pd.Timedelta(minutes=5)


@dataclass
class PatientCgm:
    patient_id: uuid.UUID
    subject_id: str
    reference_model_id: int
    secondary_model_id: int | None
    reference_name: str
    secondary_name: str | None
    reference: pd.Series
    secondary: pd.Series | None
    fingersticks: pd.Series
    meal_times: list
    hba1c: float | None
    lag: int = 0
    lag_corr: float = float("nan")
    reference_peak: float | None = None
    secondary_peak: float | None = None
    report: dict = field(default_factory=dict)


def _series(rows) -> pd.Series:
    if not rows:
        return pd.Series(dtype=float)
    times, values = zip(*rows)
    return pd.Series(np.asarray(values, dtype=float), index=pd.DatetimeIndex(times))


async def _load(s, cfg: Settings, patient_id: uuid.UUID, subject_id: str, source: str,
                offset: timedelta) -> PatientCgm | None:
    devices = (await s.execute(
        select(Device.device_id, DeviceModel.model_id, DeviceModel.manufacturer, DeviceModel.model_name,
               DeviceModel.kind, DeviceModel.nominal_interval)
        .join(DeviceModel, DeviceModel.model_id == Device.model_id)
        .where(Device.patient_id == patient_id)
    )).all()
    # Reference = the CGM with the finest sampling interval; it defines the glucose scale.
    cgms = sorted((d for d in devices if d.kind == DeviceKind.cgm), key=lambda d: d.nominal_interval)
    meters = [d for d in devices if d.kind == DeviceKind.glucometer]
    if not cgms:
        return None

    async def readings(device_id):
        return _series((await s.execute(
            select(GlucoseReading.time, GlucoseReading.glucose_mg_dl)
            .where(GlucoseReading.device_id == device_id).order_by(GlucoseReading.time)
        )).all())

    ref, sec = cgms[0], (cgms[1] if len(cgms) > 1 else None)
    meal_times = _meal_times(cfg, subject_id, offset) if source == "cgmacros" else []
    ol = v.observation_latest.c
    hba1c = await s.scalar(select(ol.value_num).where(ol.patient_id == patient_id, ol.analyte == "hba1c"))
    return PatientCgm(
        patient_id=patient_id, subject_id=subject_id,
        reference_model_id=ref.model_id, secondary_model_id=sec.model_id if sec else None,
        reference_name=f"{ref.manufacturer} {ref.model_name}",
        secondary_name=f"{sec.manufacturer} {sec.model_name}" if sec else None,
        reference=await readings(ref.device_id), secondary=await readings(sec.device_id) if sec else None,
        fingersticks=await readings(meters[0].device_id) if meters else pd.Series(dtype=float),
        meal_times=meal_times, hba1c=float(hba1c) if hba1c is not None else None,
    )


def _meal_times(cfg: Settings, subject_id: str, offset: timedelta) -> list[pd.Timestamp]:
    """Starts of meals with >= MEAL_MIN_CARBS_G carbs, in twin time. Meals are not stored
    in the twin; they are read from the source file only to time-check the CGM clocks."""
    streams = cgmacros.parse_streams(cgmacros.read_sensor_csv(cgmacros.sensor_csv_path(cfg.cgmacros_dir, subject_id)))
    meals = streams.meals[streams.meals.carbs_g.fillna(0) >= MEAL_MIN_CARBS_G]
    starts = cgmacros.shift(meals.index, offset.days, cfg.source_tz)
    return [t for t in starts if pd.notna(t)]


def _at(stream: pd.Series, t: pd.Timestamp) -> float:
    """Stream value nearest to t within tolerance (stream on a regular grid)."""
    if stream.empty:
        return float("nan")
    pos = stream.index.get_indexer([t], method="nearest")[0]
    return float(stream.iloc[pos]) if abs(stream.index[pos] - t) <= FINGERSTICK_TOLERANCE else float("nan")


def _validate(p: PatientCgm, ref: pd.Series, sec_mapped: pd.Series, fused: pd.DataFrame) -> dict:
    ref_min = cf.minute_series(ref, cf.MAX_GAP_MINUTES["reference"])
    sec_min = sec_mapped
    out = {
        "gmi_reference": round(cf.gmi(p.reference), 2),
        "gmi_secondary_raw": round(cf.gmi(p.secondary), 2),
        "gmi_fused": round(cf.gmi(fused.glucose_mg_dl), 2),
    }
    if p.hba1c is not None:
        for k in ("reference", "secondary_raw", "fused"):
            out[f"abs_diff_hba1c_{k}"] = round(abs(out[f"gmi_{k}"] - p.hba1c), 2)
    ards = {"reference": [], "secondary_mapped": [], "fused": []}
    for t, fs in p.fingersticks.items():
        for name, stream in (("reference", ref_min), ("secondary_mapped", sec_min), ("fused", fused.glucose_mg_dl)):
            v = _at(stream, t)
            if np.isfinite(v):
                ards[name].append(abs(v - fs) / fs)
    for name, values in ards.items():
        out[f"fingerstick_mard_{name}"] = round(100 * float(np.mean(values)), 1) if values else None
        out[f"fingerstick_n_{name}"] = len(values)
    reference_grid = ref_min.reindex(fused.index).notna().sum()
    out["coverage_gain_pct"] = round(100 * (len(fused) / float(reference_grid) - 1), 1) if reference_grid else None
    return out


async def _write_stream(s, patient_id, fused: pd.DataFrame) -> None:
    await s.execute(delete(GlucoseFused).where(GlucoseFused.patient_id == patient_id))
    await copy_records(
        s, GlucoseFused, ("patient_id", "time", "glucose_mg_dl", "source", "censored"),
        ((patient_id, t.to_pydatetime(), Decimal(str(v)), str(src), bool(c))
         for t, v, src, c in zip(fused.index, fused.glucose_mg_dl, fused.source, fused.censored)),
    )


async def _upsert_calibration(s, values: dict) -> None:
    stmt = insert(CgmCalibration).values(values)
    await s.execute(stmt.on_conflict_do_update(
        index_elements=[CgmCalibration.patient_id],
        set_={**{k: stmt.excluded[k] for k in values if k != "patient_id"}, "fitted_at": stmt.excluded.fitted_at},
    ))


async def _store_single(p: PatientCgm) -> dict:
    """One CGM: pass-through on the 5-min grid; the calibration row records the reference only."""
    fused = cf.single(p.reference)
    async with session_scope() as s:
        await _write_stream(s, p.patient_id, fused)
        await _upsert_calibration(s, {
            "patient_id": p.patient_id, "method_version": cf.METHOD_VERSION,
            "reference_model_id": p.reference_model_id, "reference_shift_minutes": 0,
            **{k: None for k in ("secondary_model_id", "lag_minutes", "lag_kind", "secondary_shift_minutes",
                                 "secondary_intercept", "secondary_slope", "overlap_points", "disagreement_sd",
                                 "warmup_variance_factor")},
        })
    row = {"subject_id": p.subject_id, "patient_id": str(p.patient_id), "hba1c": p.hba1c,
           "reference": p.reference_name, "secondary": None, "lag_kind": "single_cgm",
           "fused_points": len(fused), "share_censored": round(100 * float(fused.censored.mean()), 2) if len(fused) else 0,
           "gmi_reference": round(cf.gmi(p.reference), 2), "gmi_fused": round(cf.gmi(fused.glucose_mg_dl), 2)}
    if p.hba1c is not None:
        row["abs_diff_hba1c_fused"] = round(abs(row["gmi_fused"] - p.hba1c), 2)
    return row


async def run_fusion(cfg: Settings, log=print) -> list[dict]:
    async with session_scope() as s:
        patients = (await s.execute(
            select(Patient.patient_id, Patient.source_subject_id, DataSource.code, Patient.time_offset)
            .join(DataSource, DataSource.source_id == Patient.source_id)
            .order_by(Patient.source_subject_id)
        )).all()
        loaded = [p for p in [await _load(s, cfg, pid, sid, src, off) for pid, sid, src, off in patients]
                  if p is not None]

    dual = [p for p in loaded if p.secondary is not None]
    report = [await _store_single(p) for p in loaded if p.secondary is None]
    if report:
        log(f"single-CGM pass-through: {len(report)} patients")

    # Pass 1: lags and meal timing for every two-CGM patient.
    for p in dual:
        p.lag, p.lag_corr = cf.estimate_lag(p.reference, p.secondary)
        p.reference_peak = cf.meal_time_to_peak(p.reference, p.meal_times, cf.MAX_GAP_MINUTES["reference"])
        p.secondary_peak = cf.meal_time_to_peak(p.secondary, p.meal_times, cf.MAX_GAP_MINUTES["secondary"])
    typical = [pk for p in dual if abs(p.lag) <= cf.SENSOR_LAG_MAX_MINUTES
               for pk in (p.reference_peak, p.secondary_peak) if pk is not None]
    cohort_peak = statistics.median(typical) if typical else None
    log(f"cohort post-meal time-to-peak: {cohort_peak} min")

    # Pass 2: align, calibrate, fuse, store.
    for p in dual:
        align = cf.decide_alignment(p.lag, p.reference_peak, p.secondary_peak, cohort_peak)
        ref = cf.shifted(p.reference, align.reference_shift_minutes)
        sec = cf.shifted(p.secondary, align.secondary_shift_minutes)
        cal = cf.calibrate(ref, sec)
        fused = cf.fuse(ref, sec, cal)
        sec_mapped = cal.intercept + cal.slope * cf.minute_series(sec, cf.MAX_GAP_MINUTES["secondary"])

        async with session_scope() as s:
            await _write_stream(s, p.patient_id, fused)
            values = {
                "patient_id": p.patient_id, "method_version": cf.METHOD_VERSION,
                "reference_model_id": p.reference_model_id, "secondary_model_id": p.secondary_model_id,
                "lag_minutes": align.lag_minutes, "lag_kind": align.lag_kind,
                "reference_shift_minutes": align.reference_shift_minutes,
                "secondary_shift_minutes": align.secondary_shift_minutes,
                "secondary_intercept": round(cal.intercept, 2), "secondary_slope": round(cal.slope, 4),
                "overlap_points": cal.overlap_points, "disagreement_sd": round(cal.disagreement_sd, 1),
                "warmup_variance_factor": round(cal.warmup_variance_factor, 2),
            }
            await _upsert_calibration(s, values)

        row = {
            "subject_id": p.subject_id, "patient_id": str(p.patient_id), "hba1c": p.hba1c,
            "reference": p.reference_name, "secondary": p.secondary_name,
            "lag_minutes": align.lag_minutes, "lag_corr": round(p.lag_corr, 3), "lag_kind": str(align.lag_kind),
            "reference_shift_minutes": align.reference_shift_minutes,
            "secondary_shift_minutes": align.secondary_shift_minutes,
            "reference_meal_peak_min": p.reference_peak, "secondary_meal_peak_min": p.secondary_peak,
            "secondary_intercept": round(cal.intercept, 2), "secondary_slope": round(cal.slope, 4),
            "disagreement_sd": round(cal.disagreement_sd, 1),
            "warmup_variance_factor": round(cal.warmup_variance_factor, 2),
            "fused_points": len(fused),
            "share_both": round(100 * float((fused.source == "both").mean()), 1),
            "share_censored": round(100 * float(fused.censored.mean()), 2),
            **_validate(p, ref, sec_mapped, fused),
        }
        report.append(row)
        log({k: row[k] for k in ("subject_id", "lag_minutes", "lag_kind", "secondary_slope", "secondary_intercept",
                                 "gmi_fused", "hba1c", "coverage_gain_pct")})

    async with engine().connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.exec_driver_sql("CALL refresh_continuous_aggregate('ts.glucose_fused_daily', NULL, NULL)")

    _write_report(cfg, report, log)
    return report


def _write_report(cfg: Settings, report: list[dict], log) -> None:
    if not report:
        log("no patients with two CGMs; nothing fused")
        return
    out = cfg.reports_dir / "cgm_fusion_report.csv"
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(dict.fromkeys(k for r in report for k in r)))
        writer.writeheader()
        writer.writerows(report)

    dual = [r for r in report if r.get("secondary")]

    def summary(key: str) -> str:
        diffs = [r[key] for r in dual if r.get(key) is not None]
        if not diffs:
            return "n/a"
        return f"mean {np.mean(diffs):.2f}, within 0.5: {sum(d <= 0.5 for d in diffs)}/{len(diffs)}"

    log(f"two-CGM patients ({len(dual)}): |GMI - HbA1c|  reference: {summary('abs_diff_hba1c_reference')} | "
        f"secondary (raw): {summary('abs_diff_hba1c_secondary_raw')} | fused: {summary('abs_diff_hba1c_fused')}")
    if dual:
        log(f"clock offsets corrected: {[r['subject_id'] for r in dual if r['lag_kind'] == 'clock_offset']}; "
            f"mean coverage gain over reference alone: {np.mean([r['coverage_gain_pct'] for r in dual]):.1f}%")
    log(f"report: {out}")
