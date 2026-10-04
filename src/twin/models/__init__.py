"""ORM models: the single source of truth for the twin database's tables.

One module per database schema:
  base       declarative Base, shared types, enums (schema ref)
  reference  ref.*   vocabularies (data sources, tags, LOINC codes, concepts, condition groups,
                     drug classes, RxNorm medications, wearable metrics, device models)
  patient    core.*  patient master record and patient-owned data (tags, observations,
                     conditions, medications, encounters, devices, CGM calibration)
  sensors    ts.*    raw CGM readings, wearable samples and the fused CGM stream (hypertables)
  views      report.* views and ts.* continuous aggregates, read-only (own MetaData)

Conventions
  * patient_id = Synthea UUID = FHIR Patient.id
  * every timestamptz in core/ts is in "twin time" (source time + patient.time_offset)
  * derived values (age, BMI, LDL, TIR, GMI, cohort, sensor window) are never stored;
    they live in the report.* views

TimescaleDB objects and the views are created on top of these tables by
twin.db.schema.init_db.
"""

from twin.models.base import (
    AccessTier,
    Base,
    DeviceKind,
    EncounterClass,
    FusionSource,
    LagKind,
    ObservationCategory,
    Sex,
    SleepStage,
    ValueType,
)
from twin.models.patient import (
    CgmCalibration,
    Condition,
    Device,
    Encounter,
    MedicationDose,
    MedicationRegimen,
    Observation,
    Patient,
    PatientTag,
)
from twin.models.reference import (
    Concept,
    ConditionGroup,
    DataSource,
    DeviceModel,
    DrugClass,
    Medication,
    MedicationAtc,
    MedicationProduct,
    ObservationCode,
    Tag,
    WearableMetric,
)
from twin.models.sensors import (
    GlucoseFused,
    GlucoseReading,
    SleepSegment,
    WearableSample,
)

__all__ = [
    "AccessTier", "Base", "CgmCalibration", "Concept", "Condition", "ConditionGroup", "DataSource", "Device",
    "DeviceKind", "DeviceModel", "DrugClass", "Encounter", "EncounterClass", "FusionSource", "GlucoseFused",
    "GlucoseReading", "LagKind", "Medication", "MedicationAtc", "MedicationDose", "MedicationProduct",
    "MedicationRegimen", "Observation", "ObservationCategory", "ObservationCode", "Patient", "PatientTag", "Sex",
    "SleepSegment", "SleepStage", "Tag", "ValueType", "WearableMetric", "WearableSample",
]
