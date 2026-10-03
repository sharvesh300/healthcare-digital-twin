"""Schema `core`: the patient master record and everything a patient owns.

patient_id = Synthea UUID = FHIR Patient.id. Timestamps are in twin time.
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
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from twin.models.base import TIMESTAMPTZ, Base, MealType, Sex, pg_enum
from twin.models.reference import DataSource, DeviceModel, ObservationCode, Tag


class Patient(Base):
    __tablename__ = "patient"
    __table_args__ = (UniqueConstraint("source_id", "source_subject_id"), {"schema": "core"})

    patient_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    mrn: Mapped[str] = mapped_column(unique=True)
    given_name: Mapped[str]
    family_name: Mapped[str]
    name_prefix: Mapped[str | None]
    sex: Mapped[Sex] = mapped_column(pg_enum(Sex, "sex"))
    birth_date: Mapped[date]
    race_ethnicity: Mapped[str | None]
    address_city: Mapped[str | None]
    address_state: Mapped[str | None]
    address_postal: Mapped[str | None]
    source_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey(DataSource.source_id))
    source_subject_id: Mapped[str]
    time_offset: Mapped[timedelta] = mapped_column(Interval, comment="source time + time_offset = twin time")
    match_age_diff: Mapped[int] = mapped_column(
        SmallInteger, comment="audit of the match decision; EHR values are overwritten afterwards"
    )
    match_bmi_diff: Mapped[Decimal] = mapped_column(Numeric(4, 1))
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


class LabResult(Base):
    __tablename__ = "lab_result"
    __table_args__ = {"schema": "core"}

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Patient.patient_id, ondelete="CASCADE"), primary_key=True)
    code_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey(ObservationCode.code_id), primary_key=True)
    effective_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(8, 2))


class Device(Base):
    __tablename__ = "device"
    __table_args__ = (UniqueConstraint("patient_id", "model_id"), {"schema": "core"})

    device_id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Patient.patient_id, ondelete="CASCADE"))
    model_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey(DeviceModel.model_id))

    patient: Mapped[Patient] = relationship(back_populates="devices")
    model: Mapped[DeviceModel] = relationship(lazy="joined")


class Meal(Base):
    __tablename__ = "meal"
    __table_args__ = (
        UniqueConstraint("patient_id", "started_at"),
        CheckConstraint("pct_consumed BETWEEN 0 AND 100", name="pct_consumed"),
        {"schema": "core"},
    )

    meal_id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Patient.patient_id, ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    meal_type: Mapped[MealType] = mapped_column(pg_enum(MealType, "meal_type"))
    energy_kcal: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    carbs_g: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    fiber_g: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    pct_consumed: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))


class MealPhoto(Base):
    __tablename__ = "meal_photo"
    __table_args__ = {"schema": "core"}

    meal_id: Mapped[int] = mapped_column(ForeignKey(Meal.meal_id, ondelete="CASCADE"), primary_key=True)
    taken_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, primary_key=True)
    path: Mapped[str] = mapped_column(String)
