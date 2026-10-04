"""`export-features`: write the ml.* feature store to Parquet with a dataset card.

Outputs data/features/
  patient_static.parquet   one row per patient
  patient_day.parquet      one row per patient-day with CGM and/or wearable data
  series_5min.parquet      5-minute series for patients with fused CGM, plus labels
                           glucose_t30 / glucose_t60 (value 30 / 60 min ahead, if present)
  DATASET_CARD.md          provenance, sizes, missingness, splits, caveats
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import text

from twin.config import Settings
from twin.db import engine

TABLES = ("patient_static", "patient_day", "series_5min")
HORIZONS_MIN = (30, 60)


async def read_view(name: str) -> pd.DataFrame:
    async with engine().connect() as conn:
        result = await conn.execute(text(f"SELECT * FROM ml.{name}"))
        return pd.DataFrame(result.fetchall(), columns=list(result.keys()))


def add_labels(series: pd.DataFrame) -> pd.DataFrame:
    """Future glucose at +30/+60 min on the same patient's 5-minute grid (NaN if missing)."""
    series = series.sort_values(["patient_id", "time"]).reset_index(drop=True)
    for h in HORIZONS_MIN:
        future = series[["patient_id", "time", "glucose_mg_dl"]].copy()
        future["time"] = future["time"] - pd.Timedelta(minutes=h)
        series = series.merge(future.rename(columns={"glucose_mg_dl": f"glucose_t{h}"}),
                              on=["patient_id", "time"], how="left")
    return series


def _numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Decimal columns from Postgres numeric -> float, UUIDs -> str, for Parquet."""
    out = df.copy()
    for col in out.columns:
        sample = out[col].dropna().head(1)
        if sample.empty:
            continue
        kind = type(sample.iloc[0]).__name__
        if kind == "Decimal":
            out[col] = pd.to_numeric(out[col], errors="coerce").astype(float)
        elif kind == "UUID":
            out[col] = out[col].astype(str)
    return out


async def export_features(cfg: Settings, log=print) -> dict[str, int]:
    out_dir = cfg.data_dir / "features"
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = {}
    for name in TABLES:
        df = _numeric(await read_view(name))
        if name == "series_5min":
            df = add_labels(df)
        df.to_parquet(out_dir / f"{name}.parquet", index=False)
        frames[name] = df
        log(f"{name}: {len(df):,} rows x {df.shape[1]} columns -> {out_dir / (name + '.parquet')}")
    (out_dir / "DATASET_CARD.md").write_text(_card(frames))
    return {k: len(v) for k, v in frames.items()}


def _card(frames: dict[str, pd.DataFrame]) -> str:
    static = frames["patient_static"]
    lines = [
        "# Digital-twin feature store",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `twin export-features` from the `ml` schema.",
        "",
        "## Cohorts",
        "",
        "| cohort | patients | train | validation | test | with fused CGM | with ≥4 valid step days | any synthetic values |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for cohort, g in static.groupby("cohort"):
        splits = g.split.value_counts()
        lines.append(f"| {cohort} | {len(g)} | {splits.get('train', 0)} | {splits.get('validation', 0)} | "
                     f"{splits.get('test', 0)} | {(g.cgm_days > 0).sum()} | {(g.valid_step_days >= 4).sum()} | "
                     f"{g.has_synthetic_values.sum()} |")
    lines += [
        "",
        "Splits are by patient (hash of `patient_id`, 70/15/15), stable across rebuilds.",
        "",
        "## Provenance and caveats",
        "",
        "- **cgmacros**: composite twins. CGM, wearable and baseline labs are real (CGMacros);",
        "  conditions, medications and other EHR values are synthetic (Synthea). Columns",
        "  `*_is_synthetic` and `has_synthetic_values` mark this. Do not learn treatment or",
        "  comorbidity effects from these rows.",
        "- **nhanes**: real, single-source, cross-sectional (one exam per person, ~7 days of",
        "  wrist steps). Dates are nominal (NHANES publishes none). Medications are current",
        "  prescriptions at the exam; conditions are self-reported.",
        "- Glucose is the fused CGM stream (see README, CGM fusion); `glucose_censored` marks",
        "  values at the sensor reporting limits.",
        "",
        "## Tables",
        "",
    ]
    for name, df in frames.items():
        missing = (df.isna().mean() * 100).round(1)
        lines += [f"### {name} ({len(df):,} rows)", "", "| column | dtype | missing % |", "|---|---|---|"]
        lines += [f"| {c} | {df[c].dtype} | {missing[c]} |" for c in df.columns]
        lines.append("")
    return "\n".join(lines)
