"""NHANES 2011-2012 (_G) and 2013-2014 (_H): adults with diabetes.

Cohort: age >= 20 and any of: diagnosed diabetes (DIQ010 = 1), HbA1c >= 6.5 %, fasting
glucose >= 126 mg/dL, taking insulin (DIQ050) or diabetes pills (DIQ070). Probable type 1
(diagnosed before 30, on insulin, no pills) is excluded.

NHANES publishes no dates. Each participant gets a nominal exam date: the middle of the
cycle's second year, in the exam-period half the participant was seen (RIDEXMON 1 =
Nov-Apr -> February, 2 = May-Oct -> August). The wrist accelerometer was worn from the
exam day on, so step day d is exam_date + (d - 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

CYCLES = {"G": 2012, "H": 2014}  # suffix -> second calendar year of the cycle
RACE = {1: "Mexican American", 2: "Other Hispanic", 3: "Non-Hispanic White", 4: "Non-Hispanic Black",
        6: "Non-Hispanic Asian", 7: "Other race, including multi-racial"}
SNOMED = "http://snomed.info/sct"

# (component, variable, LOINC). NHANES units already equal the UCUM units of the LOINC codes.
LABS = [
    ("GHB", "LBXGH", "4548-4"), ("GLU", "LBXGLU", "1558-6"), ("INS", "LBXIN", "20448-7"),
    ("BIOPRO", "LBXSCR", "2160-0"), ("BIOPRO", "LBXSATSI", "1742-6"), ("BIOPRO", "LBXSASSI", "1920-8"),
    ("BIOPRO", "LBXSGTSI", "2324-2"), ("BIOPRO", "LBXSUA", "3084-1"), ("BIOPRO", "LBXSBU", "3094-0"),
    ("BIOPRO", "LBXSKSI", "2823-3"), ("BIOPRO", "LBXSNASI", "2951-2"),
    ("TCHOL", "LBXTC", "2093-3"), ("HDL", "LBDHDD", "2085-9"), ("TRIGLY", "LBXTR", "2571-8"),
    ("TRIGLY", "LBDLDL", "13457-7"), ("ALB_CR", "URDACT", "9318-7"),
    ("BMX", "BMXWT", "29463-7"), ("BMX", "BMXHT", "8302-2"),
]
# Self-reported conditions: (component, variable answered 1 = yes, SNOMED code, display)
CONDITIONS = [
    ("BPQ", "BPQ020", "38341003", "Hypertensive disorder"),
    ("BPQ", "BPQ080", "55822004", "Hyperlipidemia"),
    ("MCQ", "MCQ160B", "42343007", "Congestive heart failure"),
    ("MCQ", "MCQ160C", "53741008", "Coronary arteriosclerosis"),
    ("MCQ", "MCQ160D", "194828000", "Angina pectoris"),
    ("MCQ", "MCQ160E", "22298006", "Myocardial infarction"),
    ("MCQ", "MCQ160F", "230690007", "Cerebrovascular accident"),
    ("KIQ_U", "KIQ022", "709044004", "Chronic kidney disease"),
    ("DIQ", "DIQ080", "4855003", "Retinopathy due to diabetes mellitus"),
]
SMOKING = {  # SMQ020 (ever 100 cigarettes) / SMQ040 (now) -> SNOMED
    "never": ("266919005", "Never smoked tobacco"), "daily": ("449868002", "Smokes tobacco daily"),
    "occasional": ("428041000124106", "Occasional tobacco smoker"), "former": ("8517006", "Ex-smoker"),
}
T2D = ("44054006", "Type 2 diabetes mellitus")
WORN = (1, 2)  # PAXPREDM: 1 wake wear, 2 sleep wear, 3 non-wear, 4 unknown


def _clean(series: pd.Series) -> pd.Series:
    """SAS XPORT stores exact zero as ~5e-79; NHANES refused/don't-know codes are handled per variable."""
    s = pd.to_numeric(series, errors="coerce")
    return s.mask(s.abs() < 1e-70, 0.0)  # NaN (missing) stays NaN


def read(raw_dir: Path, component: str) -> pd.DataFrame:
    frames = []
    for suffix in CYCLES:
        path = raw_dir / f"{component}_{suffix}.xpt"
        if path.exists():
            df = pd.read_sas(path, format="xport", encoding="latin-1")
            df["cycle"] = suffix
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["SEQN", "cycle"])
    out = pd.concat(frames, ignore_index=True)
    out["SEQN"] = out["SEQN"].astype(int)
    return out


@dataclass(frozen=True)
class Person:
    seqn: int
    cycle: str
    sex: str
    age: int
    race_ethnicity: str | None
    exam_date: date
    diagnosed: bool
    age_at_diagnosis: int | None


def exam_date(cycle: str, exam_month_code: float | None) -> date:
    return date(CYCLES[cycle], 8 if exam_month_code == 2 else 2, 1)


def cohort(raw_dir: Path) -> tuple[list[Person], pd.DataFrame]:
    """Adults with diabetes, plus the merged per-person table used for the observations."""
    demo = read(raw_dir, "DEMO")[["SEQN", "cycle", "RIAGENDR", "RIDAGEYR", "RIDRETH3", "RIDEXMON"]]
    diq = read(raw_dir, "DIQ")
    df = demo.merge(diq, on=["SEQN", "cycle"], how="left")
    for comp in sorted({c for c, _, _ in LABS} | {"BPX", "SMQ", "BPQ", "MCQ", "KIQ_U"}):
        part = read(raw_dir, comp)
        keep = [c for c in part.columns if c not in df.columns or c in ("SEQN", "cycle")]
        df = df.merge(part[keep], on=["SEQN", "cycle"], how="left")
    for col in df.columns:
        if col not in ("SEQN", "cycle"):
            df[col] = _clean(df[col])

    adult = df.RIDAGEYR >= 20
    diabetes = (df.DIQ010 == 1) | (df.LBXGH >= 6.5) | (df.LBXGLU >= 126) | (df.DIQ050 == 1) | (df.DIQ070 == 1)
    probable_t1d = (df.DID040 < 30) & (df.DIQ050 == 1) & (df.DIQ070 != 1)
    df = df[adult & diabetes & ~probable_t1d].copy()

    people = []
    for r in df.itertuples():
        dx_age = r.DID040 if 1 <= (r.DID040 or 0) <= r.RIDAGEYR else None  # 666/777/999 = <1y/refused/unknown
        people.append(Person(
            seqn=r.SEQN, cycle=r.cycle, sex="male" if r.RIAGENDR == 1 else "female", age=int(r.RIDAGEYR),
            race_ethnicity=RACE.get(int(r.RIDRETH3)) if pd.notna(r.RIDRETH3) else None,
            exam_date=exam_date(r.cycle, r.RIDEXMON), diagnosed=r.DIQ010 == 1,
            age_at_diagnosis=int(dx_age) if dx_age is not None and pd.notna(dx_age) else None,
        ))
    return people, df.set_index("SEQN")


def imputed_birth_date(p: Person) -> date:
    """Mid-point of the possible birth dates for an age in whole years at the exam."""
    return p.exam_date - timedelta(days=round(365.25 * (p.age + 0.5)))


def exam_time(p: Person, tz: ZoneInfo) -> datetime:
    return datetime.combine(p.exam_date, time(9, 0), tzinfo=tz)


def numeric_observations(row: pd.Series) -> list[tuple[str, float]]:
    values = [(loinc, float(row[var])) for _, var, loinc in LABS if var in row and pd.notna(row[var])]
    # Blood pressure: protocol mean of the available readings (diastolic 0 = not audible).
    sys = [row[f"BPXSY{i}"] for i in range(1, 5) if pd.notna(row.get(f"BPXSY{i}"))]
    dia = [row[f"BPXDI{i}"] for i in range(1, 5) if pd.notna(row.get(f"BPXDI{i}")) and row[f"BPXDI{i}"] > 0]
    if sys:
        values.append(("8480-6", round(float(np.mean(sys)), 1)))
    if dia:
        values.append(("8462-4", round(float(np.mean(dia)), 1)))
    return values


def smoking_status(row: pd.Series) -> tuple[str, str] | None:
    ever, now = row.get("SMQ020"), row.get("SMQ040")
    if ever == 2:
        return SMOKING["never"]
    if ever == 1:
        return {1: SMOKING["daily"], 2: SMOKING["occasional"], 3: SMOKING["former"]}.get(now)
    return None


def conditions(p: Person, row: pd.Series) -> list[tuple[str, str, date]]:
    """(SNOMED code, display, onset). Onset is the diagnosis year for diabetes when reported,
    otherwise the exam date ("present by the exam")."""
    t2d_onset = p.exam_date
    if p.age_at_diagnosis is not None:
        t2d_onset = p.exam_date - timedelta(days=round(365.25 * (p.age - p.age_at_diagnosis)))
    out = [(T2D[0], T2D[1], t2d_onset)]
    out += [(code, display, p.exam_date) for _, var, code, display in CONDITIONS if row.get(var) == 1]
    return out


def prescriptions(raw_dir: Path, seqns: set[int]) -> pd.DataFrame:
    """One row per (participant, ingredient name). RXDDAYS = days taking the drug."""
    rx = read(raw_dir, "RXQ_RX")
    rx = rx[rx.SEQN.isin(seqns) & rx.RXDDRUG.notna()]
    rx = rx.assign(name=rx.RXDDRUG.astype(str).str.split(";")).explode("name")
    rx["name"] = rx["name"].str.strip()
    rx = rx[(rx["name"] != "") & (rx["name"] != "99999")]
    days = _clean(rx.RXDDAYS)
    rx["days"] = days.where((days >= 0) & (days < 77777))  # 77777/99999 refused / don't know
    return rx[["SEQN", "name", "days", "RXDDRGID"]].reset_index(drop=True)


def minute_steps(raw_dir: Path, seqns: set[int], chunksize: int = 4000):
    """Yield (SEQN, day, minute_of_day, steps, worn) for worn minutes; steps on wear
    minutes only, from the stepcount SSL model."""
    steps_path = raw_dir / "nhanes_1440_scsslsteps.csv.xz"
    wear_path = raw_dir / "nhanes_1440_PAXPREDM.csv.xz"
    minute_cols = [f"min_{i:04d}" for i in range(1, 1441)]

    def filtered(path):
        parts = [c[c.SEQN.isin(seqns)] for c in pd.read_csv(path, chunksize=chunksize)]
        return pd.concat(parts, ignore_index=True).set_index(["SEQN", "PAXDAYM"])

    steps, wear = filtered(steps_path), filtered(wear_path)
    common = steps.index.intersection(wear.index)
    for seqn, day in common:
        s = steps.loc[(seqn, day), minute_cols].to_numpy(dtype=float)
        w = wear.loc[(seqn, day), minute_cols].to_numpy(dtype=float)
        worn = np.isin(w, WORN)
        yield int(seqn), int(day), s, worn
