"""Schema `ref`: controlled vocabularies shared by every patient."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import CheckConstraint, Interval, SmallInteger, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from twin.models.base import Base, DeviceKind, pg_enum


class DataSource(Base):
    __tablename__ = "data_source"
    __table_args__ = {"schema": "ref"}

    source_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    url: Mapped[str | None]
    license: Mapped[str | None]


class Tag(Base):
    __tablename__ = "tag"
    __table_args__ = {"schema": "ref"}

    tag_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(unique=True)
    display: Mapped[str]
    description: Mapped[str | None]
    fhir_system: Mapped[str] = mapped_column(server_default="urn:healthcare-digital-twin:tags")


class ObservationCode(Base):
    __tablename__ = "observation_code"
    __table_args__ = {"schema": "ref"}

    code_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    loinc: Mapped[str] = mapped_column(unique=True)
    display: Mapped[str]
    ucum_unit: Mapped[str]


class DeviceModel(Base):
    __tablename__ = "device_model"
    __table_args__ = (
        UniqueConstraint("manufacturer", "model_name"),
        CheckConstraint("specimen IN ('interstitial', 'capillary')", name="specimen"),
        {"schema": "ref"},
    )

    model_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    manufacturer: Mapped[str]
    model_name: Mapped[str]
    kind: Mapped[DeviceKind] = mapped_column(pg_enum(DeviceKind, "device_kind"))
    specimen: Mapped[str | None]
    nominal_interval: Mapped[timedelta | None] = mapped_column(Interval)
