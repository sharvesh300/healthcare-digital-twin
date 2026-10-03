"""Async SQLAlchemy engine/session for the twin database (asyncpg driver)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from twin.config import settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def async_url(url: str) -> str:
    """Accept plain postgresql:// URLs and select the asyncpg driver."""
    u = make_url(url)
    if u.get_backend_name() == "postgresql" and u.get_driver_name() != "asyncpg":
        u = u.set(drivername="postgresql+asyncpg")
    return u.render_as_string(hide_password=False)


def engine() -> AsyncEngine:
    """Process-wide engine. The session time zone is the study's, so interval
    arithmetic and time_bucket(..., 'America/Chicago') agree with Python."""
    global _engine
    if _engine is None:
        cfg = settings()
        _engine = create_async_engine(
            async_url(cfg.database_url),
            pool_pre_ping=True,
            connect_args={"server_settings": {"timezone": cfg.source_tz}},
        )
    return _engine


async def dispose_engine() -> None:
    """Close pooled connections; call before the event loop that opened them ends."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = _sessionmaker = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """A session in one transaction: committed on success, rolled back on error."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(engine(), expire_on_commit=False)
    async with _sessionmaker() as session, session.begin():
        yield session


async def lookup(session: AsyncSession, key, value) -> dict[Any, Any]:
    """Map one column of a ref table to another, e.g. lookup(s, Tag.code, Tag.tag_id)."""
    return dict((await session.execute(select(key, value))).all())


async def copy_records(session: AsyncSession, model, columns: Sequence[str], records: Iterable[tuple]) -> int:
    """Bulk-load rows with PostgreSQL COPY on the session's own connection, so the
    load is part of the session's transaction. Used for the sensor hypertables,
    where per-row INSERTs would be ~100x slower."""
    rows = list(records)
    if not rows:
        return 0
    conn = await session.connection()
    raw = await conn.get_raw_connection()
    table = model.__table__
    await raw.driver_connection.copy_records_to_table(
        table.name, schema_name=table.schema, columns=list(columns), records=rows
    )
    return len(rows)
