"""Schema `ref`: controlled vocabularies shared by every patient (seeded from seeds/reference)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Interval,
    Numeric,
    SmallInteger,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from twin.models.base import (
    AccessTier,
    Base,
    DeviceKind,
    ObservationCategory,
    ValueType,
    pg_enum,
)


class DataSource(Base):
    __tablename__ = "data_source"
    __table_args__ = {"schema": "ref"}

    source_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    url: Mapped[str | None]
    license: Mapped[str | None]
    is_synthetic: Mapped[bool] = mapped_column(server_default=false())
    access_tier: Mapped[AccessTier] = mapped_column(pg_enum(AccessTier, "access_tier"))


class Tag(Base):
    __tablename__ = "tag"
    __table_args__ = {"schema": "ref"}

    tag_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(unique=True)
    display: Mapped[str]
    description: Mapped[str | None]
    fhir_system: Mapped[str] = mapped_column(server_default="urn:healthcare-digital-twin:tags")


class ObservationCode(Base):
    """LOINC codes the twin stores. `analyte` groups codes that measure the same thing
    (e.g. creatinine in blood 38483-4 and in serum/plasma 2160-0) for features and views."""

    __tablename__ = "observation_code"
    __table_args__ = {"schema": "ref"}

    code_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    loinc: Mapped[str] = mapped_column(unique=True)
    display: Mapped[str]
    analyte: Mapped[str] = mapped_column(index=True)
    category: Mapped[ObservationCategory] = mapped_column(pg_enum(ObservationCategory, "observation_category"))
    value_type: Mapped[ValueType] = mapped_column(pg_enum(ValueType, "value_type"))
    ucum_unit: Mapped[str | None]


class ConditionGroup(Base):
    """Clinical groupings used for features and display (hypertension, CKD, retinopathy...)."""

    __tablename__ = "condition_group"
    __table_args__ = {"schema": "ref"}

    group_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(unique=True)
    display: Mapped[str]


class Concept(Base):
    """Coded concepts from external terminologies: conditions (SNOMED CT, ICD-10-CM) and
    coded observation answers. Rows are added by the loaders as codes are met; the
    condition group comes from seeds/mappings/condition_group_map.csv."""

    __tablename__ = "concept"
    __table_args__ = (UniqueConstraint("system", "code"), {"schema": "ref"})

    concept_id: Mapped[int] = mapped_column(primary_key=True)
    system: Mapped[str]
    code: Mapped[str]
    display: Mapped[str]
    condition_group_id: Mapped[int | None] = mapped_column(SmallInteger, ForeignKey(ConditionGroup.group_id))


class DrugClass(Base):
    """Twin drug classes; a medication belongs to the class whose ATC prefix matches."""

    __tablename__ = "drug_class"
    __table_args__ = {"schema": "ref"}

    class_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(unique=True)
    display: Mapped[str]
    atc_prefix: Mapped[str] = mapped_column(unique=True)
    glucose_lowering: Mapped[bool] = mapped_column(server_default=false())


class Medication(Base):
    """Ingredient-level drug; medication_id is the RxNorm ingredient RxCUI."""

    __tablename__ = "medication"
    __table_args__ = {"schema": "ref"}

    medication_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str]
    drug_class_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey(DrugClass.class_id), comment="derived from medication_atc at init-db"
    )


class MedicationAtc(Base):
    __tablename__ = "medication_atc"
    __table_args__ = {"schema": "ref"}

    medication_id: Mapped[int] = mapped_column(ForeignKey(Medication.medication_id), primary_key=True)
    atc4: Mapped[str] = mapped_column(primary_key=True)


class MedicationProduct(Base):
    """RxNorm product (clinical/branded drug) -> ingredient(s), with per-ingredient strength."""

    __tablename__ = "medication_product"
    __table_args__ = {"schema": "ref"}

    product_rxcui: Mapped[str] = mapped_column(primary_key=True)
    medication_id: Mapped[int] = mapped_column(ForeignKey(Medication.medication_id), primary_key=True)
    display: Mapped[str]
    strength_value: Mapped[float | None] = mapped_column(Numeric(10, 3))
    strength_unit: Mapped[str | None]


class WearableMetric(Base):
    __tablename__ = "wearable_metric"
    __table_args__ = {"schema": "ref"}

    metric_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(unique=True)
    display: Mapped[str]
    unit: Mapped[str]
    loinc: Mapped[str | None]


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
    is_synthetic: Mapped[bool] = mapped_column(
        server_default=false(), comment="a generator, not a physical device (readings are synthetic)")
