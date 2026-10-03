"""Pipeline CLI. Steps are idempotent; `twin all` runs them in order."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import typer

from twin.config import settings
from twin.sources import cgmacros

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)


def _run(step: Callable[[], Awaitable[Any]]) -> Any:
    """Run async work in one event loop and close the pooled DB connections before
    the loop ends (asyncpg connections are bound to the loop that opened them)."""
    from twin.db import dispose_engine

    async def main():
        try:
            return await step()
        finally:
            await dispose_engine()

    return asyncio.run(main())


# ── steps (async) ────────────────────────────────────────────────────


async def _init_db() -> None:
    from twin.db.schema import init_db

    await init_db(log=typer.echo)


async def _match() -> None:
    from twin.pipeline.patients import run_match

    matches, unmatched = await run_match(settings())
    for m in matches:
        typer.echo(f"{m.participant.subject_id} -> {m.patient.given_name} {m.patient.family_name} "
                   f"({m.patient.patient_id}) age {m.age_diff:+d}y, BMI {m.bmi_diff:+.1f}")
    typer.echo(f"{len(matches)} matched, {len(unmatched)} unmatched "
               f"{[p.subject_id for p in unmatched] if unmatched else ''}")


async def _load_ehr(force: bool = False) -> None:
    from twin.pipeline.ehr import run_load_ehr

    typer.echo(f"{await run_load_ehr(settings(), force=force, log=typer.echo)} patient bundles loaded")


async def _load_sensors() -> None:
    from twin.pipeline.sensors import run_load_sensors

    await run_load_sensors(settings(), log=typer.echo)


async def _reconcile() -> None:
    from twin.pipeline.reconcile import run_reconcile

    await run_reconcile(settings(), log=typer.echo)


async def _summarize() -> None:
    from twin.pipeline.summaries import run_summarize

    typer.echo(await run_summarize(settings(), log=typer.echo))


# ── commands ─────────────────────────────────────────────────────────


@app.command("init-db")
def init_db() -> None:
    """Create/upgrade the twin schema (tables, hypertables, aggregates, views, ref data)."""
    _run(_init_db)


@app.command()
def ingest() -> None:
    """Validate CGMacros files and report what would be loaded (writes nothing)."""
    cfg = settings()
    participants = cgmacros.read_bio(cfg.cgmacros_dir / "bio.csv")
    typer.echo(f"{'subj':>4} {'sex':6} {'age':>3} {'A1c':>4} {'cohort':11} {'dexcom':>6} {'libre':>5} "
               f"{'fitbit':>6} {'meals':>5} {'photos':>6}  ignored")
    for sid, p in sorted(participants.items()):
        streams = cgmacros.parse_streams(cgmacros.read_sensor_csv(cgmacros.sensor_csv_path(cfg.cgmacros_dir, sid)))
        a1c = p.hba1c or 0
        cohort = "t2d" if a1c >= cfg.t2d_hba1c else "prediabetes" if a1c >= 5.7 else "normal"
        typer.echo(
            f"{sid:>4} {p.sex:6} {p.age:>3} {a1c:>4} {cohort:11} {len(streams.glucose['Dexcom GL']):>6} "
            f"{len(streams.glucose['Libre GL']):>5} {len(streams.fitbit):>6} {len(streams.meals):>5} "
            f"{len(streams.photos):>6}  {','.join(streams.ignored_columns)}"
        )
    n_t2d = sum(1 for p in participants.values() if (p.hba1c or 0) >= cfg.t2d_hba1c)
    typer.echo(f"\n{len(participants)} participants, {n_t2d} with T2D (HbA1c >= {cfg.t2d_hba1c}%)")


@app.command()
def match() -> None:
    """Match T2D participants to Synthea diabetics; create core.patient rows, tags and labs."""
    _run(_match)


@app.command("load-ehr")
def load_ehr(force: bool = typer.Option(False, help="reload bundles already in FHIR")) -> None:
    """Prune unlinked patients from FHIR, then load the matched Synthea bundles (ids = Synthea UUIDs)."""
    _run(lambda: _load_ehr(force))


@app.command("load-sensors")
def load_sensors() -> None:
    """Load devices, meals and native sensor readings into TimescaleDB (twin time)."""
    _run(_load_sensors)


@app.command()
def reconcile() -> None:
    """Write real labs, tags and race/ethnicity into FHIR; check HbA1c vs GMI."""
    _run(_reconcile)


@app.command()
def summarize() -> None:
    """Write Device resources and daily CGM / heart-rate Observations into FHIR."""
    _run(_summarize)


@app.command("all")
def run_all() -> None:
    """init-db -> ingest -> match -> load-ehr -> load-sensors -> reconcile -> summarize"""

    async def pipeline() -> None:
        steps = [("init-db", _init_db), ("ingest", None), ("match", _match), ("load-ehr", _load_ehr),
                 ("load-sensors", _load_sensors), ("reconcile", _reconcile), ("summarize", _summarize)]
        for name, step in steps:
            typer.secho(f"\n== {name}", bold=True)
            if step is None:
                ingest()
            else:
                await step()

    _run(pipeline)


@app.command()
def replay(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Serve the WebSocket live sensor feed."""
    from twin.api.replay import serve

    serve(host, port)


if __name__ == "__main__":
    app()
