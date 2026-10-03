"""ORM models: the single source of truth for the twin database's tables.

One module per database schema:
  base       declarative Base, shared types, enums (ref.sex, ref.device_kind, ref.meal_type)
  reference  ref.*   controlled vocabularies (data sources, tags, LOINC codes, device models)
  patient    core.*  patient master record and patient-owned data (tags, labs, devices, meals)
  sensors    ts.*    raw sensor readings (TimescaleDB hypertables)
  views      report.* views and ts.* continuous aggregates, read-only (own MetaData)

Conventions
  * patient_id = Synthea UUID = FHIR Patient.id
  * every timestamptz in core/ts is in "twin time" (source time + patient.time_offset)
  * derived values (age, BMI, LDL, TIR, GMI, cohort, sensor window) are never stored;
    they live in the report.* views

TimescaleDB objects and the views are created on top of these tables by
twin.db.schema.init_db.
"""

from twin.models.base import Base, DeviceKind, MealType, Sex
from twin.models.patient import Device, LabResult, Meal, MealPhoto, Patient, PatientTag
from twin.models.reference import DataSource, DeviceModel, ObservationCode, Tag
from twin.models.sensors import FitbitReading, GlucoseReading

__all__ = [
    "Base", "DataSource", "Device", "DeviceKind", "DeviceModel", "FitbitReading", "GlucoseReading",
    "LabResult", "Meal", "MealPhoto", "MealType", "ObservationCode", "Patient", "PatientTag", "Sex", "Tag",
]
