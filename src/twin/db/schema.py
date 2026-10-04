"""`init-db`: create the twin schema on the TimescaleDB instance. Idempotent.

1. timescaledb extension and the ref/core/ts/report schemas
2. tables, enums and constraints from the ORM models (create_all)
3. hypertables + compression on the ts.* reading tables
4. continuous aggregates (twin/db/sql/continuous_aggregates.sql)
5. report and ml feature-store views, recreated each time (twin/db/sql/report_views.sql,
   ml_views.sql)
6. reference data, upserted from seeds/reference/*.csv; condition concepts from
   seeds/mappings/condition_group_map.csv; drug classes assigned from ATC codes plus
   seeds/mappings/medication_class_override.csv

Schema changes to existing tables are not migrated: rebuild with scripts/reset.sh
(all twin data is regenerated from the sources).
"""

from __future__ import annotations

import csv
from datetime import timedelta
from decimal import Decimal
from importlib.resources import files
from pathlib import Path

from sqlalchemy import Boolean, Integer, Interval, Numeric, SmallInteger, select, text
from sqlalchemy.dialects.postgresql import insert

from twin.config import settings
from twin.db.engine import engine, session_scope
from twin.models import (
    Base,
    Concept,
    ConditionGroup,
    DataSource,
    DeviceModel,
    DrugClass,
    GlucoseFused,
    GlucoseReading,
    Medication,
    MedicationAtc,
    MedicationProduct,
    ObservationCode,
    Tag,
    WearableMetric,
    WearableSample,
)

SCHEMAS = ("ref", "core", "ts", "report", "ml")
HYPERTABLES = (GlucoseReading, WearableSample, GlucoseFused)

# Reference vocabularies seeded from seeds/reference/<table>.csv, in FK order.
SEED_TABLES = (
    DataSource, Tag, ObservationCode, ConditionGroup, DrugClass, Medication, MedicationAtc, MedicationProduct,
    WearableMetric, DeviceModel,
)

# A medication's twin class = the drug class whose ATC prefix matches one of its ATC-4
# codes; the lowest class_id wins, so a single-drug class beats "oral combination" (99).
ASSIGN_DRUG_CLASSES = """
UPDATE ref.medication m SET drug_class_id = (
    SELECT min(dc.class_id) FROM ref.medication_atc a
    JOIN ref.drug_class dc ON a.atc4 LIKE dc.atc_prefix || '%'
    WHERE a.medication_id = m.medication_id)
"""


def _seed_rows(model, seeds_dir: Path) -> list[dict]:
    """Read seeds/reference/<table>.csv into typed rows for `model`.

    Empty cells become NULL. Interval columns are given in minutes, in a column
    named <column>_minutes.
    """
    path = seeds_dir / "reference" / f"{model.__tablename__}.csv"
    columns = model.__table__.columns
    rows = []
    with path.open(newline="", encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            row = {}
            for col in columns:
                if isinstance(col.type, Interval):
                    value = raw.get(f"{col.name}_minutes", "")
                    row[col.name] = timedelta(minutes=int(value)) if value else None
                elif col.name in raw:
                    row[col.name] = _typed(col, raw[col.name])
            rows.append(row)
    if not rows:
        raise ValueError(f"{path} has no rows")
    return rows


def _typed(col, value: str):
    if value == "":
        return None
    if isinstance(col.type, Boolean):
        return value.strip().lower() in ("true", "t", "1", "yes")
    if isinstance(col.type, (SmallInteger, Integer)):
        return int(value)
    if isinstance(col.type, Numeric):
        return Decimal(value)
    return value


def _concept_rows(seeds_dir: Path, groups: dict[str, int]) -> list[dict]:
    path = seeds_dir / "mappings" / "condition_group_map.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        return [{"system": r["system"], "code": r["code"], "display": r["display"],
                 "condition_group_id": groups[r["group_code"]]} for r in csv.DictReader(fh)]


def _class_overrides(seeds_dir: Path) -> list[dict]:
    """Reviewed exceptions where RxClass has no usable ATC class (seeds/mappings)."""
    path = seeds_dir / "mappings" / "medication_class_override.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [{"mid": int(r["medication_id"]), "cls": r["drug_class_code"]} for r in csv.DictReader(fh)]


def _statements(resource: str) -> list[str]:
    sql = files("twin.db").joinpath("sql", resource).read_text()
    return [s.strip() for s in sql.split(";\n") if s.strip() and not all(
        line.strip().startswith("--") or not line.strip() for line in s.splitlines())]


async def _upsert(session, model, rows: list[dict], key: list[str] | None = None) -> None:
    key = key or [c.name for c in model.__table__.primary_key]
    for start in range(0, len(rows), 1000):  # stay well under the bind-parameter limit
        stmt = insert(model).values(rows[start:start + 1000])
        updates = {c: stmt.excluded[c] for c in rows[0] if c not in key}
        await session.execute(stmt.on_conflict_do_update(index_elements=key, set_=updates) if updates
                              else stmt.on_conflict_do_nothing(index_elements=key))


async def init_db(log=print) -> None:
    # DDL that TimescaleDB requires outside a transaction block -> autocommit.
    async with engine().connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS timescaledb")
        for schema in SCHEMAS:
            await conn.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        await conn.run_sync(Base.metadata.create_all)
        log(f"tables: {len(Base.metadata.tables)}")

        for model in HYPERTABLES:
            name = f"{model.__table__.schema}.{model.__table__.name}"
            await conn.execute(
                text("SELECT create_hypertable(:t, by_range('time', INTERVAL '7 days'), if_not_exists => TRUE)"),
                {"t": name},
            )
            compressed = await conn.scalar(
                text("SELECT compression_enabled FROM timescaledb_information.hypertables "
                     "WHERE hypertable_schema = :s AND hypertable_name = :n"),
                {"s": model.__table__.schema, "n": model.__table__.name},
            )
            if not compressed:
                # Segment compressed chunks by the series key (device[, metric] for raw, patient for fused).
                segment = ", ".join(c.name for c in model.__table__.primary_key if c.name != "time")
                await conn.exec_driver_sql(
                    f"ALTER TABLE {name} SET (timescaledb.compress, timescaledb.compress_segmentby = '{segment}')"
                )
        log(f"hypertables: {', '.join(m.__tablename__ for m in HYPERTABLES)}")

        aggregates = _statements("continuous_aggregates.sql")
        for stmt in aggregates:
            await conn.exec_driver_sql(stmt)
        # View-only schemas are rebuilt from SQL every time (ml depends on report).
        await conn.exec_driver_sql("DROP SCHEMA ml CASCADE")
        await conn.exec_driver_sql("DROP SCHEMA report CASCADE")
        await conn.exec_driver_sql("CREATE SCHEMA report")
        await conn.exec_driver_sql("CREATE SCHEMA ml")
        views = _statements("report_views.sql")
        ml_views = _statements("ml_views.sql")
        for stmt in views + ml_views:
            await conn.exec_driver_sql(stmt)
        log(f"continuous aggregates: {len(aggregates)}, report views: {len(views)}, ml views: {len(ml_views)}")

    seeds_dir = settings().seeds_dir
    async with session_scope() as s:
        for model in SEED_TABLES:
            rows = _seed_rows(model, seeds_dir)
            await _upsert(s, model, rows)
            log(f"seeded ref.{model.__tablename__}: {len(rows)} rows")
        groups = dict((await s.execute(select(ConditionGroup.code, ConditionGroup.group_id))).all())
        concepts = _concept_rows(seeds_dir, groups)
        await _upsert(s, Concept, concepts, key=["system", "code"])
        log(f"seeded ref.concept (condition groups): {len(concepts)} rows")
        await s.execute(text(ASSIGN_DRUG_CLASSES))
        overrides = _class_overrides(seeds_dir)
        if overrides:
            await s.execute(text(
                "UPDATE ref.medication m SET drug_class_id = dc.class_id FROM ref.drug_class dc "
                "WHERE m.medication_id = :mid AND dc.code = :cls"), overrides)
        log(f"drug classes assigned ({len(overrides)} manual overrides)")
