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


async def _ingest_bigideas() -> None:
    from twin.pipeline.bigideas import run_ingest_bigideas

    await run_ingest_bigideas(settings(), log=typer.echo)


async def _simulate_wearables() -> None:
    from twin.pipeline.simulate import run_simulate_wearables

    await run_simulate_wearables(settings(), log=typer.echo)


async def _load_ehr(force: bool = False) -> None:
    from twin.pipeline.ehr import run_load_ehr

    typer.echo(f"{await run_load_ehr(settings(), force=force, log=typer.echo)} patient bundles loaded")


async def _copy_ehr() -> None:
    from twin.pipeline.ehr import run_copy_ehr

    await run_copy_ehr(settings(), log=typer.echo)


async def _ingest_nhanes() -> None:
    from twin.pipeline.nhanes import run_ingest_nhanes

    await run_ingest_nhanes(settings(), log=typer.echo)


async def _load_sensors() -> None:
    from twin.pipeline.sensors import run_load_sensors

    await run_load_sensors(settings(), log=typer.echo)


async def _fuse_cgm() -> None:
    from twin.pipeline.fusion import run_fusion

    await run_fusion(settings(), log=typer.echo)


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
               f"{'fitbit':>6}  ignored")
    for sid, p in sorted(participants.items()):
        streams = cgmacros.parse_streams(cgmacros.read_sensor_csv(cgmacros.sensor_csv_path(cfg.cgmacros_dir, sid)))
        a1c = p.hba1c or 0
        cohort = "t2d" if a1c >= cfg.t2d_hba1c else "prediabetes" if a1c >= 5.7 else "normal"
        typer.echo(
            f"{sid:>4} {p.sex:6} {p.age:>3} {a1c:>4} {cohort:11} {len(streams.glucose['Dexcom GL']):>6} "
            f"{len(streams.glucose['Libre GL']):>5} {len(streams.fitbit):>6}  {','.join(streams.ignored_columns)}"
        )
    n_t2d = sum(1 for p in participants.values() if (p.hba1c or 0) >= cfg.t2d_hba1c)
    typer.echo(f"\n{len(participants)} participants, {n_t2d} with T2D (HbA1c >= {cfg.t2d_hba1c}%)")


@app.command()
def match() -> None:
    """Match T2D participants to Synthea diabetics; create core.patient rows, tags and labs."""
    _run(_match)


@app.command("ingest-bigideas")
def ingest_bigideas() -> None:
    """BIG IDEAs participants as composite twins: real Dexcom G6 + Empatica E4 (HR, IBI, skin temp, EDA)."""
    _run(_ingest_bigideas)


@app.command("simulate-wearables")
def simulate_wearables() -> None:
    """SYNTHETIC sleep, SpO2, respiration, stress and nightly HRV for every composite twin (flagged)."""
    _run(_simulate_wearables)


@app.command("load-ehr")
def load_ehr(force: bool = typer.Option(False, help="reload bundles already in FHIR")) -> None:
    """Prune unlinked patients from FHIR, then load the matched Synthea bundles (ids = Synthea UUIDs)."""
    _run(lambda: _load_ehr(force))


@app.command("copy-ehr")
def copy_ehr() -> None:
    """Copy composite twins' Synthea observations, conditions, medications and encounters into the twin DB."""
    _run(_copy_ehr)


@app.command("ingest-nhanes")
def ingest_nhanes() -> None:
    """Load NHANES 2011-2014 adults with diabetes: labs, BP, conditions, medications, minute steps."""
    _run(_ingest_nhanes)


@app.command("load-sensors")
def load_sensors() -> None:
    """Load devices, meals and native sensor readings into TimescaleDB (twin time)."""
    _run(_load_sensors)


@app.command("fuse-cgm")
def fuse_cgm() -> None:
    """Fuse each patient's two CGMs (align, cross-calibrate, combine) into ts.glucose_fused."""
    _run(_fuse_cgm)


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
    """init-db -> ingest -> match -> ingest-bigideas -> load-ehr -> copy-ehr -> load-sensors -> ingest-nhanes -> fuse-cgm -> simulate-wearables -> reconcile -> summarize"""

    async def pipeline() -> None:
        steps = [("init-db", _init_db), ("ingest", None), ("match", _match), ("ingest-bigideas", _ingest_bigideas), ("load-ehr", _load_ehr), ("copy-ehr", _copy_ehr),
                 ("load-sensors", _load_sensors), ("ingest-nhanes", _ingest_nhanes), ("fuse-cgm", _fuse_cgm), ("simulate-wearables", _simulate_wearables),
                 ("reconcile", _reconcile),
                 ("summarize", _summarize)]
        for name, step in steps:
            typer.secho(f"\n== {name}", bold=True)
            if step is None:
                ingest()
            else:
                await step()

    _run(pipeline)


@app.command("export-features")
def export_features() -> None:
    """Write the ml.* feature store to data/features/*.parquet with a dataset card."""
    from twin.ml.features import export_features as run

    _run(lambda: run(settings(), log=typer.echo))


@app.command("train-baselines")
def train_baselines() -> None:
    """Train the baseline models from data/features: glucose forecaster, NHANES HbA1c model."""
    import pandas as pd

    from twin.ml import forecast, population

    cfg = settings()
    features = cfg.data_dir / "features"
    if not (features / "series_5min.parquet").exists():
        raise typer.BadParameter("no feature store; run `twin export-features` first")
    typer.secho("== glucose forecaster (fused CGM, patient-grouped CV)", bold=True)
    forecast.train(pd.read_parquet(features / "series_5min.parquet"), cfg, log=typer.echo)
    typer.secho("== population HbA1c model (NHANES)", bold=True)
    population.train(pd.read_parquet(features / "patient_static.parquet"), cfg, log=typer.echo)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Serve the twin API: /patients, /twin/{id} (+timeline, simulations), WebSocket replay."""
    from twin.api.replay import serve as run

    run(host, port)


@app.command(hidden=True)
def replay(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Alias of `serve`."""
    serve(host, port)


if __name__ == "__main__":
    app()
