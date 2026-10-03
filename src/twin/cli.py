"""Pipeline CLI. Steps are idempotent; `twin all` runs them in order."""

from __future__ import annotations

import typer

from twin import cgmacros
from twin.config import settings

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)


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
    from twin.patients import run_match

    matches, unmatched = run_match(settings())
    for m in matches:
        typer.echo(f"{m.participant.subject_id} -> {m.patient.given_name} {m.patient.family_name} "
                   f"({m.patient.patient_id}) age {m.age_diff:+d}y, BMI {m.bmi_diff:+.1f}")
    typer.echo(f"{len(matches)} matched, {len(unmatched)} unmatched "
               f"{[p.subject_id for p in unmatched] if unmatched else ''}")


@app.command("load-ehr")
def load_ehr(force: bool = typer.Option(False, help="reload bundles already in FHIR")) -> None:
    """Load the matched patients' Synthea bundles into HAPI FHIR (ids = Synthea UUIDs)."""
    from twin.ehr import run_load_ehr

    typer.echo(f"{run_load_ehr(settings(), force=force, log=typer.echo)} patient bundles loaded")


@app.command("load-sensors")
def load_sensors() -> None:
    """Load devices, meals and native sensor readings into TimescaleDB (twin time)."""
    from twin.timeseries import run_load_sensors

    run_load_sensors(settings(), log=typer.echo)


@app.command()
def reconcile() -> None:
    """Write real labs, tags and race/ethnicity into FHIR; check HbA1c vs GMI."""
    from twin.reconcile import run_reconcile

    run_reconcile(settings(), log=typer.echo)


@app.command()
def summarize() -> None:
    """Write Device resources and daily CGM / heart-rate Observations into FHIR."""
    from twin.summaries import run_summarize

    typer.echo(run_summarize(settings(), log=typer.echo))


@app.command("all")
def run_all() -> None:
    """ingest -> match -> load-ehr -> load-sensors -> reconcile -> summarize"""
    for step in (ingest, match, load_ehr, load_sensors, reconcile, summarize):
        typer.secho(f"\n== {step.__name__.replace('_', '-')}", bold=True)
        step() if step is not load_ehr else load_ehr(force=False)


@app.command()
def replay(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Serve the WebSocket live sensor feed."""
    from twin.replay import serve

    serve(host, port)


if __name__ == "__main__":
    app()
