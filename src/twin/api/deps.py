"""Shared dependencies: the live-twin services created in the app's lifespan (twin.api.replay).
Tests replace them through `app.dependency_overrides`."""

from __future__ import annotations

from starlette.requests import HTTPConnection

from twin.streaming.manager import PatientTwinStateManager
from twin.streaming.store import SqlIngestor


def twin_manager(conn: HTTPConnection) -> PatientTwinStateManager:
    return conn.app.state.twin


def ingestor(conn: HTTPConnection) -> SqlIngestor:
    return conn.app.state.ingestor
