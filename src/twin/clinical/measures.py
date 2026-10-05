"""What the record shows for each test or vital sign: its name, panel, unit and adult
reference range, and how a result is flagged.

A *measure* is what a person reads as one test. Most are one analyte (``ldl``); blood
pressure is two (``sbp`` and ``dbp``), read and flagged together. Analytes not listed here
still appear, under "Other", named from their LOINC display.

Ranges are general adult reference intervals for display only (not diagnostic cut-offs);
sex-specific ones are given per sex. A bound of None means "no limit on that side".
"""

from __future__ import annotations

from dataclasses import dataclass, field

Range = tuple[float | None, float | None]

PANELS: dict[str, str] = {
    "glycaemic": "Glycaemic",
    "lipids": "Lipids",
    "kidney": "Kidney",
    "liver": "Liver",
    "blood": "Blood and electrolytes",
    "cardiac": "Cardiac",
    "vitals": "Vital signs",
    "cgm": "CGM",
    "exam": "Examinations",
    "lifestyle": "Lifestyle",
    "other": "Other",
}


@dataclass(frozen=True)
class Measure:
    key: str
    display: str
    panel: str
    analytes: tuple[str, ...]
    unit: str | None = None
    digits: int = 0
    range: Range | None = None
    range_by_sex: dict[str, Range] = field(default_factory=dict)
    # twin drug classes that move this measure (for "related medications")
    drug_classes: tuple[str, ...] = ()

    def range_for(self, sex: str | None) -> Range | None:
        return self.range_by_sex.get(sex or "", self.range)


GLUCOSE_LOWERING = ("biguanide", "sulfonylurea", "alpha_glucosidase_inhibitor", "thiazolidinedione",
                    "dpp4_inhibitor", "glp1_ra", "sglt2_inhibitor", "other_glucose_lowering", "insulin_rapid",
                    "insulin_intermediate", "insulin_premixed", "insulin_long", "oral_combination")
# what moves glucose: the glucose-lowering classes, and glucocorticoids, which raise it
GLYCAEMIC = (*GLUCOSE_LOWERING, "systemic_corticosteroid")
LIPID_LOWERING = ("statin",)
ANTIHYPERTENSIVE = ("ace_inhibitor", "arb", "calcium_channel_blocker", "thiazide_diuretic", "beta_blocker")

_M = [
    # glycaemic
    Measure("hba1c", "HbA1c", "glycaemic", ("hba1c",), "%", 1, (4.0, 5.6), drug_classes=GLYCAEMIC),
    Measure("glucose_fasting", "Fasting glucose", "glycaemic", ("glucose_fasting",), "mg/dL", 0, (70, 99),
            drug_classes=GLYCAEMIC),
    Measure("glucose", "Glucose", "glycaemic", ("glucose",), "mg/dL", 0, (70, 99), drug_classes=GLYCAEMIC),
    Measure("glucose_2h_postprandial", "Glucose, 2 h after a meal", "glycaemic", ("glucose_2h_postprandial",),
            "mg/dL", 0, (None, 139), drug_classes=GLYCAEMIC),
    Measure("insulin", "Insulin", "glycaemic", ("insulin",), "µIU/mL", 1, (2.6, 24.9)),
    Measure("c_peptide", "C-peptide", "glycaemic", ("c_peptide",), "ng/mL", 2, (0.8, 3.85)),
    Measure("glycated_albumin", "Glycated albumin", "glycaemic", ("glycated_albumin",), "%", 1, (11, 16)),
    # lipids
    Measure("cholesterol_total", "Total cholesterol", "lipids", ("cholesterol_total",), "mg/dL", 0, (None, 199),
            drug_classes=LIPID_LOWERING),
    Measure("ldl", "LDL cholesterol", "lipids", ("ldl",), "mg/dL", 0, (None, 99), drug_classes=LIPID_LOWERING),
    Measure("hdl", "HDL cholesterol", "lipids", ("hdl",), "mg/dL", 0, (40, None), drug_classes=LIPID_LOWERING),
    Measure("triglycerides", "Triglycerides", "lipids", ("triglycerides",), "mg/dL", 0, (None, 149),
            drug_classes=LIPID_LOWERING),
    # kidney
    Measure("creatinine", "Creatinine", "kidney", ("creatinine",), "mg/dL", 2,
            range_by_sex={"female": (0.59, 1.04), "male": (0.74, 1.35)}),
    Measure("egfr_reported", "eGFR", "kidney", ("egfr_reported",), "mL/min/1.73 m²", 0, (60, None)),
    Measure("bun", "Urea nitrogen (BUN)", "kidney", ("bun",), "mg/dL", 0, (7, 20)),
    Measure("uacr", "Albumin/creatinine ratio (UACR)", "kidney", ("uacr",), "mg/g", 0, (None, 29),
            drug_classes=("ace_inhibitor", "arb", "sglt2_inhibitor")),
    Measure("uric_acid", "Uric acid", "kidney", ("uric_acid",), "mg/dL", 1,
            range_by_sex={"female": (2.4, 6.0), "male": (3.4, 7.0)}),
    # liver
    Measure("alt", "ALT", "liver", ("alt",), "U/L", 0, (7, 55)),
    Measure("ast", "AST", "liver", ("ast",), "U/L", 0, (8, 48)),
    Measure("ggt", "GGT", "liver", ("ggt",), "U/L", 0, (None, 60)),
    # blood and electrolytes
    Measure("hemoglobin", "Haemoglobin", "blood", ("hemoglobin",), "g/dL", 1,
            range_by_sex={"female": (12.0, 15.5), "male": (13.5, 17.5)}),
    Measure("sodium", "Sodium", "blood", ("sodium",), "mmol/L", 0, (135, 145)),
    Measure("potassium", "Potassium", "blood", ("potassium",), "mmol/L", 1, (3.5, 5.1)),
    Measure("crp_hs", "hs-CRP", "blood", ("crp_hs",), "mg/L", 1, (None, 3.0)),
    # cardiac
    Measure("nt_probnp", "NT-proBNP", "cardiac", ("nt_probnp",), "pg/mL", 0, (None, 125)),
    Measure("troponin_t_hs", "Troponin T (hs)", "cardiac", ("troponin_t_hs",), "ng/L", 0, (None, 14)),
    # vital signs
    Measure("blood_pressure", "Blood pressure", "vitals", ("sbp", "dbp"), "mmHg", 0, drug_classes=ANTIHYPERTENSIVE),
    Measure("heart_rate", "Heart rate", "vitals", ("heart_rate",), "/min", 0, (60, 100)),
    Measure("heart_rate_resting", "Resting heart rate", "vitals", ("heart_rate_resting",), "/min", 0, (60, 100)),
    Measure("respiratory_rate", "Respiratory rate", "vitals", ("respiratory_rate",), "/min", 0, (12, 20)),
    Measure("spo2", "SpO₂", "vitals", ("spo2",), "%", 0, (95, None)),
    Measure("weight", "Weight", "vitals", ("weight",), "kg", 1),
    Measure("height", "Height", "vitals", ("height",), "cm", 0),
    Measure("bmi", "BMI", "vitals", ("bmi",), "kg/m²", 1, (18.5, 24.9)),
    # CGM summaries
    Measure("cgm_mean", "Mean glucose (CGM)", "cgm", ("cgm_mean",), "mg/dL", 0, (None, 154)),
    Measure("gmi", "GMI", "cgm", ("gmi",), "%", 1, (None, 7.0)),
    Measure("cgm_tir", "Time in range", "cgm", ("cgm_tir",), "%", 0, (70, None)),
    Measure("cgm_tar_level1", "Time above range", "cgm", ("cgm_tar_level1",), "%", 0, (None, 25)),
    Measure("cgm_tar_level2", "Time very high", "cgm", ("cgm_tar_level2",), "%", 0, (None, 5)),
    Measure("cgm_tbr_level1", "Time below range", "cgm", ("cgm_tbr_level1",), "%", 0, (None, 4)),
    Measure("cgm_tbr_level2", "Time very low", "cgm", ("cgm_tbr_level2",), "%", 0, (None, 1)),
    Measure("cgm_cv", "Glucose variability (CV)", "cgm", ("cgm_cv",), "%", 0, (None, 36)),
    # examinations and lifestyle (coded answers have no range)
    Measure("retinopathy_left", "Retina, left eye", "exam", ("retinopathy_left",)),
    Measure("retinopathy_right", "Retina, right eye", "exam", ("retinopathy_right",)),
    Measure("smoking_status", "Smoking status", "lifestyle", ("smoking_status",)),
    Measure("steps", "Steps", "lifestyle", ("steps",), "steps", 0),
    Measure("sleep_duration", "Sleep duration", "lifestyle", ("sleep_duration",), "min", 0),
]

MEASURES: dict[str, Measure] = {m.key: m for m in _M}
# analyte -> the measure it belongs to
BY_ANALYTE: dict[str, Measure] = {a: m for m in _M for a in m.analytes}

# Blood pressure is flagged per component: stage-1 hypertension from 130 systolic or 80 diastolic.
COMPONENT_RANGES: dict[str, Range] = {"sbp": (None, 129), "dbp": (None, 79)}

# Measures that track each condition group (for "related tests" on a diagnosis).
GROUP_MEASURES: dict[str, tuple[str, ...]] = {
    "t2d": ("hba1c", "glucose_fasting", "glucose", "cgm_tir", "gmi"),
    "prediabetes": ("hba1c", "glucose_fasting", "glucose"),
    "hypertension": ("blood_pressure",),
    "dyslipidemia": ("ldl", "cholesterol_total", "hdl", "triglycerides"),
    "obesity": ("bmi", "weight"),
    "metabolic_syndrome": ("blood_pressure", "triglycerides", "hdl", "glucose_fasting", "bmi"),
    "ckd": ("egfr_reported", "uacr", "creatinine"),
    "retinopathy": ("retinopathy_left", "retinopathy_right", "hba1c"),
    "neuropathy": ("hba1c",),
    "cardiovascular": ("blood_pressure", "ldl", "nt_probnp"),
    "masld": ("alt", "ast", "ggt"),
    "hypoglycemia": ("glucose", "cgm_tbr_level1", "cgm_tbr_level2"),
    "anemia": ("hemoglobin",),
}


def measure_for(analyte: str, loinc_display: str | None = None) -> Measure:
    """The measure an analyte belongs to; unknown analytes get a plain one under "Other"."""
    return BY_ANALYTE.get(analyte) or Measure(analyte, loinc_display or analyte.replace("_", " ").capitalize(),
                                              "other", (analyte,))


def _flag(value: float, rng: Range | None) -> str | None:
    if rng is None:
        return None
    lo, hi = rng
    if lo is not None and value < lo:
        return "low"
    if hi is not None and value > hi:
        return "high"
    return "normal"


def flag(measure: Measure, values: dict[str, float], sex: str | None = None) -> str | None:
    """"high", "low", "normal", or None when the measure has no range (or no value).
    A multi-analyte measure is high if any component is high, else low if any is low."""
    if not values:
        return None
    if len(measure.analytes) > 1:
        flags = {_flag(v, COMPONENT_RANGES.get(a)) for a, v in values.items()}
        return "high" if "high" in flags else "low" if "low" in flags else "normal" if "normal" in flags else None
    (value,) = values.values()
    return _flag(value, measure.range_for(sex))
