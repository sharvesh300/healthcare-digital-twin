"""Declarative base, shared column types and the enum types (schema `ref`)."""

from __future__ import annotations

import enum

from sqlalchemy import Enum, MetaData, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import DeclarativeBase

TIMESTAMPTZ = TIMESTAMP(timezone=True)


class Base(DeclarativeBase):
    type_annotation_map = {str: Text}
    metadata = MetaData(
        naming_convention={
            "pk": "%(table_name)s_pkey",
            "fk": "%(table_name)s_%(column_0_name)s_fkey",
            "uq": "%(table_name)s_%(column_0_N_name)s_key",
            "ck": "%(table_name)s_%(constraint_name)s_check",
            "ix": "%(table_name)s_%(column_0_N_name)s_idx",
        }
    )


class Sex(enum.StrEnum):
    female = "female"
    male = "male"


class DeviceKind(enum.StrEnum):
    cgm = "cgm"
    glucometer = "glucometer"
    wearable = "wearable"


class MealType(enum.StrEnum):
    breakfast = "breakfast"
    lunch = "lunch"
    dinner = "dinner"
    snack = "snack"


def pg_enum(cls: type[enum.Enum], name: str) -> Enum:
    """A PostgreSQL enum type in the ref schema, stored by value."""
    return Enum(cls, name=name, schema="ref", values_callable=lambda e: [m.value for m in e])
