"""`init-db`: create the twin schema on the TimescaleDB instance. Idempotent.

1. timescaledb extension and the ref/core/ts/report schemas
2. tables, enums and constraints from the ORM models (create_all)
3. hypertables + compression on the ts.* reading tables
4. continuous aggregates (twin/db/sql/continuous_aggregates.sql)
5. report views, recreated each time (twin/db/sql/report_views.sql)
6. reference data, upserted from seeds/reference/*.csv
"""

from __future__ import annotations

import csv
from datetime import timedelta
from importlib.resources import files
from pathlib import Path

from sqlalchemy import Interval, SmallInteger, text
from sqlalchemy.dialects.postgresql import insert

from twin.config import settings
from twin.db.engine import engine, session_scope
from twin.models import (
    Base,
    DataSource,
    DeviceModel,
    FitbitReading,
    GlucoseReading,
    ObservationCode,
    Tag,
)

SCHEMAS = ("ref", "core", "ts", "report")
HYPERTABLES = (GlucoseReading, FitbitReading)

# Reference vocabularies seeded from seeds/reference/<table>.csv, in FK order.
SEED_TABLES = (DataSource, Tag, ObservationCode, DeviceModel)


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
                    value = raw[col.name]
                    row[col.name] = None if value == "" else int(value) if isinstance(col.type, SmallInteger) else value
            rows.append(row)
    if not rows:
        raise ValueError(f"{path} has no rows")
    return rows


def _statements(resource: str) -> list[str]:
    sql = files("twin.db").joinpath("sql", resource).read_text()
    return [s.strip() for s in sql.split(";\n") if s.strip() and not all(
        line.strip().startswith("--") or not line.strip() for line in s.splitlines())]


async def _upsert(session, model, rows: list[dict]) -> None:
    stmt = insert(model).values(rows)
    pk = [c.name for c in model.__table__.primary_key]
    await session.execute(
        stmt.on_conflict_do_update(index_elements=pk, set_={c: stmt.excluded[c] for c in rows[0] if c not in pk})
    )


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
                await conn.exec_driver_sql(
                    f"ALTER TABLE {name} SET (timescaledb.compress, timescaledb.compress_segmentby = 'device_id')"
                )
        log(f"hypertables: {', '.join(m.__tablename__ for m in HYPERTABLES)}")

        for stmt in _statements("continuous_aggregates.sql"):
            await conn.exec_driver_sql(stmt)
        await conn.exec_driver_sql("DROP SCHEMA report CASCADE")
        await conn.exec_driver_sql("CREATE SCHEMA report")
        views = _statements("report_views.sql")
        for stmt in views:
            await conn.exec_driver_sql(stmt)
        log(f"continuous aggregates: 2, report views: {len(views)}")

    seeds_dir = settings().seeds_dir
    async with session_scope() as s:
        for model in SEED_TABLES:
            rows = _seed_rows(model, seeds_dir)
            await _upsert(s, model, rows)
            log(f"seeded ref.{model.__tablename__}: {len(rows)} rows")
