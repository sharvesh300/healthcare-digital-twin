"""Schema `ts`: raw sensor streams, keyed by device (the device knows its patient).

These tables become TimescaleDB hypertables in twin.db.schema.init_db.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from twin.models.base import TIMESTAMPTZ, Base
from twin.models.patient import Device


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


class FitbitReading(Base):
    """Fitbit export differs per participant: METs for most, a 0-3 intensity level
    (sedentary/light/moderate/vigorous) for others. Both are measured, neither derivable."""

    __tablename__ = "fitbit_reading"
    __table_args__ = (
        CheckConstraint("heart_rate BETWEEN 25 AND 250", name="heart_rate"),
        CheckConstraint("mets >= 0", name="mets"),
        CheckConstraint("activity_level BETWEEN 0 AND 3", name="activity_level"),
        CheckConstraint("active_kcal >= 0", name="active_kcal"),
        CheckConstraint("num_nonnulls(heart_rate, mets, activity_level, active_kcal) > 0", name="any_value"),
        {"schema": "ts"},
    )

    device_id: Mapped[int] = mapped_column(ForeignKey(Device.device_id, ondelete="CASCADE"), primary_key=True)
    time: Mapped[datetime] = mapped_column(TIMESTAMPTZ, primary_key=True)
    heart_rate: Mapped[int | None] = mapped_column(SmallInteger)
    mets: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    activity_level: Mapped[int | None] = mapped_column(SmallInteger)
    active_kcal: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
