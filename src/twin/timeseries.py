"""`load-sensors` step: devices, meals and raw readings into TimescaleDB (twin time)."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from twin import cgmacros
from twin.config import Settings
from twin.db import connect
from twin.patients import load_participants

# CGMacros column / stream -> (manufacturer, model_name) in ref.device_model
DEXCOM = ("Dexcom", "G6 Pro")
LIBRE = ("Abbott", "FreeStyle Libre Pro")
CONTOUR = ("Ascensia", "Contour Next")
FITBIT = ("Fitbit", "Sense")
CGM_MODELS = {"Dexcom GL": DEXCOM, "Libre GL": LIBRE}


def _ensure_device(conn, patient_id, model: tuple[str, str]) -> int:
    row = conn.execute(
        """
        INSERT INTO core.device (patient_id, model_id)
        SELECT %s, model_id FROM ref.device_model WHERE manufacturer = %s AND model_name = %s
        ON CONFLICT (patient_id, model_id) DO UPDATE SET patient_id = EXCLUDED.patient_id
        RETURNING device_id
        """,
        (patient_id, *model),
    ).fetchone()
    return row[0]


def _none(value):
    return None if value is None or (isinstance(value, float) and np.isnan(value)) else value


def _load_patient(conn, cfg: Settings, patient_id, subject_id: str, offset_days: int, participant) -> dict:
    df = cgmacros.read_sensor_csv(cgmacros.sensor_csv_path(cfg.cgmacros_dir, subject_id))
    streams = cgmacros.parse_streams(df)
    tz = cfg.source_tz
    stats = {"subject": subject_id}

    devices = {}
    for model in (*CGM_MODELS.values(), CONTOUR, FITBIT):
        devices[model] = _ensure_device(conn, patient_id, model)
    device_ids = list(devices.values())

    # Idempotent reload: replace this patient's rows wholesale.
    conn.execute("DELETE FROM ts.glucose_reading WHERE device_id = ANY(%s)", (device_ids,))
    conn.execute("DELETE FROM ts.fitbit_reading WHERE device_id = ANY(%s)", (device_ids,))
    conn.execute("DELETE FROM core.meal WHERE patient_id = %s", (patient_id,))

    with conn.cursor() as cur:
        with cur.copy("COPY ts.glucose_reading (device_id, time, glucose_mg_dl) FROM STDIN") as cp:
            for column, model in CGM_MODELS.items():
                series = streams.glucose[column]
                times = cgmacros.shift(series.index, offset_days, tz)
                n = 0
                for t, value in zip(times, series.to_numpy()):
                    if pd.notna(t):
                        cp.write_row((devices[model], t.to_pydatetime(), int(value)))
                        n += 1
                stats[column] = n
            # Fingersticks from bio.csv happen on study day 1.
            day1 = streams.study_day_1 + timedelta(days=offset_days)
            for clock, value in participant.fingersticks:
                cp.write_row((devices[CONTOUR], datetime.combine(day1, clock, tzinfo=cfg.tz), int(round(value))))
            stats["fingerstick"] = len(participant.fingersticks)

        fitbit = streams.fitbit.copy()
        fitbit.index = cgmacros.shift(fitbit.index, offset_days, tz)
        fitbit = fitbit[fitbit.index.notna()]
        with cur.copy(
            "COPY ts.fitbit_reading (device_id, time, heart_rate, mets, activity_level, active_kcal) FROM STDIN"
        ) as cp:
            for t, row in zip(fitbit.index, fitbit.itertuples(index=False)):
                hr, mets, level, kcal = (_none(v) for v in row)
                cp.write_row(
                    (
                        devices[FITBIT], t.to_pydatetime(),
                        int(hr) if hr is not None else None, mets,
                        int(level) if level is not None else None, kcal,
                    )
                )
        stats["fitbit"] = len(fitbit)

        meals = streams.meals.copy()
        meals.index = cgmacros.shift(meals.index, offset_days, tz)
        meals = meals[meals.index.notna()]
        meal_ids: list[tuple[pd.Timestamp, int]] = []
        for t, m in zip(meals.index, meals.itertuples(index=False)):
            row = cur.execute(
                """
                INSERT INTO core.meal (patient_id, started_at, meal_type, energy_kcal, carbs_g,
                                       protein_g, fat_g, fiber_g, pct_consumed)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (patient_id, started_at) DO NOTHING
                RETURNING meal_id
                """,
                (patient_id, t.to_pydatetime(), m.meal_type, _none(m.energy_kcal), _none(m.carbs_g),
                 _none(m.protein_g), _none(m.fat_g), _none(m.fiber_g), _none(m.pct_consumed)),
            ).fetchone()
            if row:
                meal_ids.append((t, row[0]))
        stats["meals"] = len(meal_ids)

        # Each photo belongs to the most recent meal start at or before it
        # (the start photo shares the meal's timestamp; the end photo follows it).
        photos = streams.photos.copy()
        photos.index = cgmacros.shift(photos.index, offset_days, tz)
        photos = photos[photos.index.notna()]
        starts = pd.DatetimeIndex([t for t, _ in meal_ids])
        attached = 0
        for t, path in photos.items():
            pos = starts.searchsorted(t, side="right") - 1
            if pos < 0:
                continue
            cur.execute(
                "INSERT INTO core.meal_photo (meal_id, taken_at, path) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (meal_ids[pos][1], t.to_pydatetime(), f"CGMacros-{subject_id}/{path}"),
            )
            attached += 1
        stats["photos"] = attached
    stats["ignored_columns"] = ",".join(streams.ignored_columns)
    return stats


def run_load_sensors(cfg: Settings, log=print) -> list[dict]:
    participants = load_participants(cfg)
    results = []
    with connect() as conn:
        patients = conn.execute(
            """
            SELECT p.patient_id, p.source_subject_id, extract(day FROM p.time_offset)::int
            FROM core.patient p JOIN ref.data_source s USING (source_id)
            WHERE s.code = 'cgmacros' ORDER BY p.source_subject_id
            """
        ).fetchall()
        for patient_id, subject_id, offset_days in patients:
            stats = _load_patient(conn, cfg, patient_id, subject_id, offset_days, participants[subject_id])
            conn.commit()
            results.append(stats)
            log(stats)

    # Continuous-aggregate refresh and policies cannot run inside a transaction.
    with connect(autocommit=True) as conn:
        for view in ("ts.glucose_daily", "ts.fitbit_daily"):
            conn.execute(f"CALL refresh_continuous_aggregate('{view}', NULL, NULL)")
        for table in ("ts.glucose_reading", "ts.fitbit_reading"):
            conn.execute(
                f"SELECT add_compression_policy('{table}', compress_after => INTERVAL '30 days', if_not_exists => true)"
            )
    return results
