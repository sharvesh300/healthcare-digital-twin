"""Schema `ts`: sensor streams (TimescaleDB hypertables, see twin.db.schema.init_db).

Raw readings are keyed by device (the device knows its patient). The fused CGM
stream combines a patient's devices, and the meal log is self-reported, so both are
keyed by patient.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Numeric, SmallInteger, false
from sqlalchemy.orm import Mapped, mapped_column

from twin.models.base import TIMESTAMPTZ, Base, FusionSource, MealType, SleepStage, TwinSignal, pg_enum
from twin.models.patient import Device, Patient
from twin.models.reference import WearableMetric


class GlucoseReading(Base):
    """CGM (interstitial) and fingerstick (capillary) readings; specimen via device_model."""

    __tablename__ = "glucose_reading"
    __table_args__ = (
        CheckConstraint("glucose_mg_dl BETWEEN 20 AND 600", name="glucose_mg_dl"),
        {"schema": "ts"},
    )

    device_id: Mapped[int] = mapped_column(ForeignKey(Device.device_id, ondelete="CASCADE"), primary_key=True)
    time: Mapped[datetime] = mapped_column(TIMESTAMPTZ, primary_key=True)
    glucose_mg_dl: Mapped[int] = mapped_column(SmallInteger)


class WearableSample(Base):
    """One wearable measurement: (device, metric, time) -> value in the metric's unit.

    Long form because wearables export different metrics (Fitbit: HR, METs or intensity,
    active kcal; Garmin: steps, HR, SpO2, stress, respiration; ActiGraph: steps).
    """

    __tablename__ = "wearable_sample"
    __table_args__ = {"schema": "ts"}

    device_id: Mapped[int] = mapped_column(ForeignKey(Device.device_id, ondelete="CASCADE"), primary_key=True)
    metric_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey(WearableMetric.metric_id), primary_key=True)
    time: Mapped[datetime] = mapped_column(TIMESTAMPTZ, primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(10, 3))


class GlucoseFused(Base):
    """One glucose estimate per patient every 5 minutes from the calibrated CGMs.

    Derived data (twin.analytics.cgm_fusion), materialised because it depends on fitted
    parameters (core.cgm_calibration). `censored` marks values pinned at a sensor's
    40/400 mg/dL reporting limit.
    """

    __tablename__ = "glucose_fused"
    __table_args__ = (
        CheckConstraint("glucose_mg_dl BETWEEN 20 AND 600", name="glucose_mg_dl"),
        {"schema": "ts"},
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Patient.patient_id, ondelete="CASCADE"), primary_key=True)
    time: Mapped[datetime] = mapped_column(TIMESTAMPTZ, primary_key=True)
    glucose_mg_dl: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    source: Mapped[FusionSource] = mapped_column(pg_enum(FusionSource, "fusion_source"))
    censored: Mapped[bool] = mapped_column(server_default=false())


class Meal(Base):
    """A meal as the participant logged it (CGMacros food log, real), at the photo's time.

    Keyed by patient, not device: the log is self-reported. Macros are the log's values for
    the whole meal, as recorded. CGMacros' `Amount Consumed` is not stored, because it mixes
    0-4 codes with percentages.
    """

    __tablename__ = "meal"
    __table_args__ = (
        *(CheckConstraint(f"{c} >= 0", name=c) for c in ("energy_kcal", "carbs_g", "protein_g", "fat_g", "fiber_g")),
        {"schema": "ts"},
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Patient.patient_id, ondelete="CASCADE"), primary_key=True)
    time: Mapped[datetime] = mapped_column(TIMESTAMPTZ, primary_key=True)
    meal_type: Mapped[MealType] = mapped_column(pg_enum(MealType, "meal_type"))
    energy_kcal: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    carbs_g: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    fiber_g: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))


class SleepSegment(Base):
    """A contiguous sleep stage from a wearable (or the twin's wearable generator)."""

    __tablename__ = "sleep_segment"
    __table_args__ = (
        CheckConstraint("end_time > start_time", name="positive_duration"),
        {"schema": "ts"},
    )

    device_id: Mapped[int] = mapped_column(ForeignKey(Device.device_id, ondelete="CASCADE"), primary_key=True)
    start_time: Mapped[datetime] = mapped_column(TIMESTAMPTZ, primary_key=True)
    end_time: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    stage: Mapped[SleepStage] = mapped_column(pg_enum(SleepStage, "sleep_stage"))


class TwinStateTransition(Base):
    """A status change of the live twin (glucose in_range -> high, sleep light -> deep, a signal
    going stale), recorded when the twin publishes it. Readings themselves are in the tables
    above; this is the record of what the twin concluded from them (twin.streaming.state)."""

    __tablename__ = "twin_state_transition"
    __table_args__ = {"schema": "ts"}

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Patient.patient_id, ondelete="CASCADE"), primary_key=True)
    signal: Mapped[TwinSignal] = mapped_column(pg_enum(TwinSignal, "twin_signal"), primary_key=True)
    time: Mapped[datetime] = mapped_column(TIMESTAMPTZ, primary_key=True, comment="device time of the change")
    from_status: Mapped[str | None]
    to_status: Mapped[str]
    value: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), comment="the signal's value at the change")
    state_version: Mapped[int] = mapped_column(BigInteger, comment="twin state version that published it")
