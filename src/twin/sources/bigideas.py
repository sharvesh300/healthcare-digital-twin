"""BIG IDEAs Glycemic Variability and Wearable Device Data (PhysioNet 1.1.2, ODC-By).

16 adults aged 35-65 (women post-menopausal) with elevated glucose or prediabetes, each
wearing a Dexcom G6 CGM and an Empatica E4 wristband for ~10 days. Demographics give
only sex and HbA1c (no age or BMI).

Files per participant (NNN): Dexcom_NNN.csv (5-min CGM export), HR_NNN.csv (E4 heart rate,
minute timestamps), IBI_NNN.csv (inter-beat intervals in seconds, one row per detected beat),
TEMP_NNN.csv and EDA_NNN.csv (4 Hz). Timestamps are local time at the study site (Duke,
North Carolina -> America/New_York).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

TZ = "America/New_York"
IBI_RANGE_MS = (300, 2000)  # physiologically plausible beat-to-beat intervals


@dataclass(frozen=True)
class Participant:
    subject_id: str  # "001".."016"
    sex: str  # 'female' | 'male'
    hba1c: float


def read_demographics(raw_dir: Path) -> list[Participant]:
    with (raw_dir / "Demographics.csv").open(newline="", encoding="utf-8-sig") as fh:
        return [Participant(f"{int(r['ID']):03d}", r["Gender"].strip().lower(), float(r["HbA1c"]))
                for r in csv.DictReader(fh)]


def path(raw_dir: Path, subject_id: str, kind: str) -> Path:
    return raw_dir / subject_id / f"{kind}_{subject_id}.csv"


def read_dexcom(file: Path) -> pd.Series:
    """Estimated glucose values (EGV rows), mg/dL, indexed by naive local time."""
    df = pd.read_csv(file, low_memory=False)
    ts_col = next(c for c in df.columns if c.startswith("Timestamp"))
    val_col = next(c for c in df.columns if c.startswith("Glucose Value"))
    egv = df[df["Event Type"] == "EGV"]
    values = egv[val_col].replace({"Low": 40, "High": 400})
    s = pd.Series(pd.to_numeric(values, errors="coerce").to_numpy(),
                  index=pd.to_datetime(egv[ts_col], format="ISO8601")).dropna()
    return s[~s.index.duplicated()].sort_index()


def _read(file: Path) -> pd.DataFrame:
    df = pd.read_csv(file, low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    return df


def read_heart_rate(file: Path) -> pd.Series:
    """Per-minute mean heart rate (the E4 export repeats minute timestamps)."""
    df = _read(file)
    t = pd.to_datetime(df["datetime"], format="mixed")
    return pd.to_numeric(df["hr"], errors="coerce").groupby(t.dt.floor("min")).mean().dropna()


def read_ibi(file: Path) -> pd.Series:
    """Inter-beat intervals in ms at each beat, outside the plausible range dropped."""
    df = _read(file)
    ms = pd.to_numeric(df["ibi"], errors="coerce") * 1000
    s = pd.Series(ms.to_numpy(), index=pd.to_datetime(df["datetime"], format="mixed")).dropna()
    s = s[(s >= IBI_RANGE_MS[0]) & (s <= IBI_RANGE_MS[1])]
    return s[~s.index.duplicated()].sort_index().round(1)


def read_minute_mean(file: Path, column: str, chunksize: int = 500_000) -> pd.Series:
    """4 Hz signal (TEMP, EDA) -> per-minute mean, read in chunks."""
    sums, counts = [], []
    for chunk in pd.read_csv(file, chunksize=chunksize, low_memory=False):
        chunk.columns = [c.strip() for c in chunk.columns]
        minute = pd.to_datetime(chunk["datetime"], format="mixed").dt.floor("min")
        values = pd.to_numeric(chunk[column], errors="coerce")
        grouped = values.groupby(minute)
        sums.append(grouped.sum())
        counts.append(grouped.count())
    total = pd.concat(sums).groupby(level=0).sum()
    n = pd.concat(counts).groupby(level=0).sum()
    return (total / n.where(n > 0)).dropna()


def shift(index: pd.DatetimeIndex, days: int) -> pd.DatetimeIndex:
    """Naive site-local time -> tz-aware twin time, preserving wall-clock time. Times that do not
    exist (spring-forward hour) or are ambiguous (fall-back hour) on the target date become NaT
    and are dropped by the loaders, rather than being piled onto a neighbouring timestamp."""
    return (index + pd.Timedelta(days=days)).tz_localize(TZ, ambiguous="NaT", nonexistent="NaT")
