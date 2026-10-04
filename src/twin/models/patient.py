"""Schema `core`: the patient master record and everything a patient owns.

One row in core.patient per real person (or per composite twin). Every clinical row
carries `source_id`, so its origin and whether it is synthetic (ref.data_source) are
always known. Timestamps are in twin time.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Interval,
    Numeric,
    SmallInteger,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from twin.models.base import TIMESTAMPTZ, Base, EncounterClass, LagKind, Sex, pg_enum
from twin.models.reference import (
    Concept,
    DataSource,
    DeviceModel,
    Medication,
    ObservationCode,
    Tag,
)


class Patient(Base):
    """Identity and demographics. Sources without names or exact birth dates (NHANES,
    ShanghaiT2DM) leave the name/MRN empty and store a mid-year birth date flagged as
    imputed. match_* columns are only set for composite (CGMacros + Synthea) twins."""

    __tablename__ = "patient"
    __table_args__ = (
        UniqueConstraint("source_id", "source_subject_id"),
        CheckConstraint("num_nonnulls(match_age_diff, match_bmi_diff) IN (0, 2)", name="match_audit"),
        {"schema": "core"},
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    mrn: Mapped[str | None] = mapped_column(unique=True)
    given_name: Mapped[str | None]
    family_name: Mapped[str | None]
    name_prefix: Mapped[str | None]
    sex: Mapped[Sex] = mapped_column(pg_enum(Sex, "sex"))
    birth_date: Mapped[date]
    birth_date_imputed: Mapped[bool] = mapped_column(server_default=false())
    race_ethnicity: Mapped[str | None]
    address_city: Mapped[str | None]
    address_state: Mapped[str | None]
    address_postal: Mapped[str | None]
    source_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey(DataSource.source_id))
    source_subject_id: Mapped[str]
    time_offset: Mapped[timedelta] = mapped_column(
        Interval, server_default=text("'0'::interval"), comment="source time + time_offset = twin time"
    )
    match_age_diff: Mapped[int | None] = mapped_column(
        SmallInteger, comment="composite twins: audit of the match decision"
    )
    match_bmi_diff: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    fhir_synced_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())

    source: Mapped[DataSource] = relationship()
    tags: Mapped[list[Tag]] = relationship(secondary="core.patient_tag", viewonly=True)
    devices: Mapped[list[Device]] = relationship(back_populates="patient", passive_deletes=True)


class PatientTag(Base):
    __tablename__ = "patient_tag"
    __table_args__ = (Index(None, "tag_id"), {"schema": "core"})

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Patient.patient_id, ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey(Tag.tag_id), primary_key=True)
    assigned_by: Mapped[str] = mapped_column(server_default="pipeline")
    assigned_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())


class Observation(Base):
    """Labs, vital signs, survey/exam answers: one value per (patient, code, time).
    Exactly one of value_num (in the code's UCUM unit) or value_concept_id is set."""

    __tablename__ = "observation"
    __table_args__ = (
        CheckConstraint("num_nonnulls(value_num, value_concept_id) = 1", name="one_value"),
        Index(None, "code_id"),
        {"schema": "core"},
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Patient.patient_id, ondelete="CASCADE"), primary_key=True)
    code_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey(ObservationCode.code_id), primary_key=True)
    effective_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, primary_key=True)
    value_num: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    value_concept_id: Mapped[int | None] = mapped_column(ForeignKey(Concept.concept_id))
    source_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey(DataSource.source_id))


class Condition(Base):
    """Diagnoses, comorbidities and complications (SNOMED CT / ICD-10-CM concepts)."""

    __tablename__ = "condition"
    __table_args__ = (
        CheckConstraint("abated_at IS NULL OR abated_at >= onset_at", name="abatement_after_onset"),
        {"schema": "core"},
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Patient.patient_id, ondelete="CASCADE"), primary_key=True)
    concept_id: Mapped[int] = mapped_column(ForeignKey(Concept.concept_id), primary_key=True)
    onset_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, primary_key=True)
    abated_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    source_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey(DataSource.source_id))


class MedicationRegimen(Base):
    """A prescribed/standing medication at ingredient level. Combination products give one
    row per ingredient. dose_value is per administration, in dose_unit."""

    __tablename__ = "medication_regimen"
    __table_args__ = (
        UniqueConstraint("patient_id", "source_id", "source_ref", "medication_id"),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="end_after_start"),
        CheckConstraint("times_per_day IS NULL OR times_per_day > 0", name="times_per_day"),
        {"schema": "core"},
    )

    regimen_id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Patient.patient_id, ondelete="CASCADE"))
    medication_id: Mapped[int] = mapped_column(ForeignKey(Medication.medication_id))
    started_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    ended_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    dose_value: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    dose_unit: Mapped[str | None]
    times_per_day: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    as_needed: Mapped[bool] = mapped_column(server_default=false())
    source_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey(DataSource.source_id))
    source_ref: Mapped[str] = mapped_column(comment="id of the source record, for idempotent reloads")


class MedicationDose(Base):
    """A single administered dose with its time (e.g. an insulin injection)."""

    __tablename__ = "medication_dose"
    __table_args__ = (CheckConstraint("dose_value > 0", name="dose_value"), {"schema": "core"})

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Patient.patient_id, ondelete="CASCADE"), primary_key=True)
    medication_id: Mapped[int] = mapped_column(ForeignKey(Medication.medication_id), primary_key=True)
    time: Mapped[datetime] = mapped_column(TIMESTAMPTZ, primary_key=True)
    dose_value: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    dose_unit: Mapped[str]
    route: Mapped[str | None]
    source_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey(DataSource.source_id))


class Encounter(Base):
    """Visits, for the patient timeline."""

    __tablename__ = "encounter"
    __table_args__ = (
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="end_after_start"),
        Index(None, "patient_id", "started_at"),
        {"schema": "core"},
    )

    encounter_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Patient.patient_id, ondelete="CASCADE"))
    encounter_class: Mapped[EncounterClass] = mapped_column(pg_enum(EncounterClass, "encounter_class"))
    started_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    ended_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    source_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey(DataSource.source_id))


class Device(Base):
    __tablename__ = "device"
    __table_args__ = (UniqueConstraint("patient_id", "model_id"), {"schema": "core"})

    device_id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Patient.patient_id, ondelete="CASCADE"))
    model_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey(DeviceModel.model_id))

    patient: Mapped[Patient] = relationship(back_populates="devices")
    model: Mapped[DeviceModel] = relationship(lazy="joined")


class CgmCalibration(Base):
    """Per-patient parameters of the CGM fusion (twin.analytics.cgm_fusion).

    The reference CGM defines the glucose scale; the secondary CGM is shifted in time
    and mapped onto it (glucose_ref = intercept + slope * glucose_secondary). The two
    devices are identified by (patient_id, model_id), the natural key of core.device.
    With a single CGM all secondary_* / alignment columns are NULL (pass-through).
    """

    __tablename__ = "cgm_calibration"
    __table_args__ = (
        CheckConstraint("secondary_model_id IS NULL OR reference_model_id <> secondary_model_id",
                        name="distinct_models"),
        CheckConstraint("warmup_variance_factor >= 1", name="warmup_variance_factor"),
        CheckConstraint(
            "num_nulls(secondary_model_id, lag_minutes, lag_kind, secondary_shift_minutes, secondary_intercept, "
            "secondary_slope, overlap_points, disagreement_sd, warmup_variance_factor) IN (0, 9)",
            name="secondary_all_or_none"),
        {"schema": "core"},
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Patient.patient_id, ondelete="CASCADE"), primary_key=True)
    method_version: Mapped[str]
    reference_model_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey(DeviceModel.model_id))
    secondary_model_id: Mapped[int | None] = mapped_column(SmallInteger, ForeignKey(DeviceModel.model_id))
    lag_minutes: Mapped[int | None] = mapped_column(SmallInteger, comment="secondary behind reference (+) or ahead (-)")
    lag_kind: Mapped[LagKind | None] = mapped_column(pg_enum(LagKind, "lag_kind"))
    reference_shift_minutes: Mapped[int] = mapped_column(SmallInteger)
    secondary_shift_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    secondary_intercept: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    secondary_slope: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    overlap_points: Mapped[int | None]
    disagreement_sd: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), comment="mg/dL, after calibration, post warm-up")
    warmup_variance_factor: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), comment="error-variance multiplier for a sensor in its first 24 h"
    )
    fitted_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
