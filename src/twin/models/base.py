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


class AccessTier(enum.StrEnum):
    open = "open"
    registered = "registered"  # free, after sign-up and agreement
    controlled = "controlled"  # approved application
    generated = "generated"  # produced locally (synthetic)


class ObservationCategory(enum.StrEnum):
    laboratory = "laboratory"
    vital_signs = "vital-signs"
    activity = "activity"
    survey = "survey"
    exam = "exam"


class ValueType(enum.StrEnum):
    numeric = "numeric"
    coded = "coded"


class EncounterClass(enum.StrEnum):
    ambulatory = "ambulatory"
    emergency = "emergency"
    inpatient = "inpatient"
    virtual = "virtual"
    home = "home"


class SleepStage(enum.StrEnum):
    awake = "awake"
    light = "light"
    deep = "deep"
    rem = "rem"


class LagKind(enum.StrEnum):
    """How the time difference between two CGMs was interpreted."""

    sensor_lag = "sensor_lag"  # physiological/processing delay (minutes)
    clock_offset = "clock_offset"  # device clock or time-zone error


class FusionSource(enum.StrEnum):
    """Which calibrated sensor(s) a fused glucose value came from."""

    both = "both"
    reference_only = "reference_only"
    secondary_only = "secondary_only"


class MealType(enum.StrEnum):
    breakfast = "breakfast"
    lunch = "lunch"
    dinner = "dinner"
    snack = "snack"


class TwinSignal(enum.StrEnum):
    """A live-twin signal whose status can change (ts.twin_state_transition)."""

    glucose = "glucose"  # band: very_low, low, in_range, high, very_high; or stale
    glucose_trend = "glucose_trend"  # rising_fast, rising, steady, falling, falling_fast
    heart_rate = "heart_rate"  # low, normal, elevated; or stale
    activity = "activity"  # sedentary, light, moderate, vigorous
    sleep = "sleep"  # awake, light, deep, rem
    spo2 = "spo2"  # low, borderline, normal


def pg_enum(cls: type[enum.Enum], name: str) -> Enum:
    """A PostgreSQL enum type in the ref schema, stored by value."""
    return Enum(cls, name=name, schema="ref", values_callable=lambda e: [m.value for m in e])
