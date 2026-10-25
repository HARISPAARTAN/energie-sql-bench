"""Command line interface `esb`. Commands import their modules lazily so the CLI starts fast."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import typer

if TYPE_CHECKING:
    from energie_sql_bench.config import Settings

app = typer.Typer(
    help="Energie-SQL-Bench: Text-to-SQL-Benchmark auf dem Energiewende-Warehouse.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Energie-SQL-Bench."""


@app.command()
def version() -> None:
    """Version ausgeben."""
    from energie_sql_bench import __version__

    typer.echo(__version__)


@app.command("guard-check")
def guard_check(sql: str) -> None:
    """Eine SQL-Anweisung gegen den Guard prüfen (Exit 0 erlaubt, 1 blockiert)."""
    from energie_sql_bench.guard import check_sql

    result = check_sql(sql)
    typer.echo(("ERLAUBT" if result.allowed else "BLOCKIERT") + f": {result.reason}")
    if result.tables:
        typer.echo("Tabellen: " + ", ".join(result.tables))
    raise typer.Exit(0 if result.allowed else 1)


schema_app = typer.Typer(help="Schema der Datenbank", no_args_is_help=True)
gold_app = typer.Typer(help="Gold-Ergebnisse", no_args_is_help=True)
app.add_typer(schema_app, name="schema")
app.add_typer(gold_app, name="gold")


@schema_app.callback()
def schema_main() -> None:
    """Schema der Datenbank."""


@gold_app.callback()
def gold_main() -> None:
    """Gold-Ergebnisse."""


@schema_app.command("dump")
def schema_dump() -> None:
    """Schema von dw und rpt nach schema/schema.json schreiben (bench_reader)."""
    from functools import partial

    from energie_sql_bench.config import load_settings
    from energie_sql_bench.execute import connect_mssql, fetch_all
    from energie_sql_bench.files import write_json
    from energie_sql_bench.schema import dump_schema

    settings = load_settings()
    con = connect_mssql(settings.db)
    try:
        schema = dump_schema(partial(fetch_all, con), settings.db.name)
    finally:
        con.close()
    write_json(settings.path("schema/schema.json"), schema)
    fks = sum(len(t["foreign_keys"]) for t in schema["tables"].values())
    typer.echo(f"{len(schema['tables'])} Tabellen und Sichten, {fks} Fremdschlüssel geschrieben")


def _live_fingerprint(settings: Settings) -> dict:
    from functools import partial

    from energie_sql_bench.execute import connect_mssql, fetch_all
    from energie_sql_bench.snapshot import compute_fingerprint

    con = connect_mssql(settings.db)
    try:
        return compute_fingerprint(partial(fetch_all, con), settings.snapshot)
    finally:
        con.close()


@app.command()
def snapshot(
    check: Annotated[
        bool, typer.Option("--check", help="Nur mit snapshot/fingerprint.json vergleichen")
    ] = False,
) -> None:
    """Fingerabdruck des Datenschnitts schreiben oder prüfen."""
    from energie_sql_bench.config import load_settings
    from energie_sql_bench.files import read_json, write_json
    from energie_sql_bench.gold import load_gold, stale_gold
    from energie_sql_bench.snapshot import compare_fingerprints

    settings = load_settings()
    live = _live_fingerprint(settings)
    path = settings.path("snapshot/fingerprint.json")
    if not check:
        write_json(path, live)
        typer.echo(f"Fingerabdruck {live['digest']} geschrieben")
        return
    stored = read_json(path)
    diffs = compare_fingerprints(stored, live)
    stale = stale_gold(load_gold(settings.path("bench/gold")), stored.get("digest", ""))
    if stale:
        diffs.append(
            f"Gold-Dateien mit anderem Snapshot als {stored.get('digest')} eingefroren: {', '.join(stale)}"
        )
    for line in diffs[:50]:
        typer.echo(line)
    typer.echo("Snapshot unverändert" if not diffs else f"{len(diffs)} Abweichungen")
    raise typer.Exit(1 if diffs else 0)


@gold_app.command("build")
def gold_build(
    only: Annotated[str | None, typer.Option(help="Komma-getrennte IDs, zum Beispiel q001,q002")] = None,
    refreeze: Annotated[
        bool, typer.Option("--refreeze", help="Gold-Dateien eines älteren Snapshots neu einfrieren")
    ] = False,
) -> None:
    """Gold-SQL zweimal ausführen, Gegenprobe vergleichen, bench/gold/*.json schreiben."""
    from energie_sql_bench.config import load_settings
    from energie_sql_bench.execute import MssqlExecutor
    from energie_sql_bench.files import read_json
    from energie_sql_bench.gold import build_gold, load_gold, stale_gold, write_gold
    from energie_sql_bench.questions import load_questions
    from energie_sql_bench.snapshot import compare_fingerprints

    settings = load_settings()
    stored = read_json(settings.path("snapshot/fingerprint.json"))
    diffs = compare_fingerprints(stored, _live_fingerprint(settings))
    if diffs:
        typer.echo(f"Snapshot weicht ab ({len(diffs)} Abweichungen): esb snapshot --check")
        raise typer.Exit(1)
    stale = stale_gold(load_gold(settings.path("bench/gold")), stored["digest"])
    if stale and not refreeze:
        typer.echo(
            f"Gold wurde mit einem anderen Snapshot als {stored['digest']} eingefroren: {', '.join(stale)}. "
            "Der Datenschnitt hat sich geändert; bei gewollter Neueinfrierung: esb gold build --refreeze"
        )
        raise typer.Exit(1)
    questions = load_questions(settings.path("bench/questions"))
    if only:
        wanted = {x.strip() for x in only.split(",")}
        questions = [q for q in questions if q.id in wanted]
    executor = MssqlExecutor(settings.db)
    try:
        entries, errors = build_gold(
            questions, executor, stored["digest"], settings.gold_max_rows, settings.compare
        )
    finally:
        executor.close()
    write_gold(entries, settings.path("bench/gold"))
    for line in errors:
        typer.echo(line)
    typer.echo(f"{len(entries)} Gold-Dateien geschrieben, {len(errors)} Fehler")
    raise typer.Exit(1 if errors else 0)


@app.command()
def run(
    provider: Annotated[str, typer.Option(help="anthropic, ollama oder synthetic")],
    variant: Annotated[str, typer.Option(help="v1 bis v6")] = "v4",
    model: Annotated[str | None, typer.Option(help="Modell-ID; Standard je Provider")] = None,
    split: Annotated[str, typer.Option(help="test, dev oder all")] = "test",
    lang: Annotated[str, typer.Option(help="Sprachen, Komma-getrennt")] = "de,en",
    repeat: Annotated[int, typer.Option(help="Wiederholungen")] = 1,
    self_correct: Annotated[bool, typer.Option("--self-correct", help="bis zu zwei Reparaturen")] = False,
    max_usd: Annotated[float | None, typer.Option(help="Kostenobergrenze in USD")] = None,
    limit: Annotated[int | None, typer.Option(help="nur die ersten N Items (Entwicklung)")] = None,
    run_id: Annotated[str | None, typer.Option(help="Name des Laufordners")] = None,
) -> None:
    """Einen Lauf gegen die lokale Datenbank ausführen und unter results/runs/ aufzeichnen."""
    import datetime as dt

    from energie_sql_bench.config import load_settings
    from energie_sql_bench.llm import default_model
    from energie_sql_bench.llm.base import ProviderError
    from energie_sql_bench.runner import RunError, RunSpec, default_run_id, live_run, preflight_estimate

    settings = load_settings()
    model = model or default_model(provider, settings)
    spec = RunSpec(
        run_id=run_id or default_run_id(provider, model, variant, self_correct, split, dt.date.today()),
        provider=provider,
        model=model,
        variant=variant,
        split=split,
        langs=tuple(x.strip() for x in lang.split(",") if x.strip()),
        repeats=repeat,
        self_correct=self_correct,
        max_usd=settings.cost.max_run_usd if max_usd is None else max_usd,
        limit=limit,
    )
    try:
        estimate = preflight_estimate(settings, spec)
        typer.echo(
            f"Lauf {spec.run_id}: Kostenschätzung (obere Grenze, ohne Cache) {estimate:.2f} USD, "
            f"Grenze {spec.max_usd:.2f} USD"
        )
        run_dir, summary = live_run(settings, spec)
    except (RunError, ProviderError) as exc:
        typer.echo(f"Abbruch: {exc}")
        raise typer.Exit(1) from exc
    except KeyboardInterrupt as exc:
        typer.echo(
            f"Unterbrochen. Bezahlte Antworten liegen in results/partial/{spec.run_id}; "
            "derselbe Befehl mit derselben --run-id setzt den Lauf fort."
        )
        raise typer.Exit(130) from exc
    ex = summary["ex"]
    typer.echo(
        f"EX {ex['mean']:.6f} ({ex['correct']}/{ex['n']}), EX-strict {summary['ex_strict']['mean']:.6f}, "
        f"Kosten {summary['cost']['usd']:.4f} USD"
    )
    if not summary["complete"]:
        typer.echo(f"Unvollständig: {summary['aborted_reason']}")
    typer.echo(f"Aufgezeichnet in {run_dir}")


@app.command()
def replay(
    run_id: Annotated[str | None, typer.Argument(help="Laufordner unter results/runs/")] = None,
    all_runs: Annotated[bool, typer.Option("--all", help="alle aufgezeichneten Läufe")] = False,
) -> None:
    """Aufgezeichnete Läufe offline neu bewerten und mit summary.json vergleichen."""
    from energie_sql_bench.config import load_settings
    from energie_sql_bench.runner import list_runs, replay_run, summaries_equal

    settings = load_settings()
    run_ids = list_runs(settings) if all_runs else [run_id] if run_id else []
    if not run_ids:
        typer.echo("Kein Lauf angegeben (RUN_ID oder --all)")
        raise typer.Exit(2)
    failed = 0
    for rid in run_ids:
        recomputed, stored = replay_run(settings, rid)
        same = summaries_equal(recomputed, stored)
        failed += not same
        typer.echo(("OK " if same else "ABWEICHUNG ") + rid)
    raise typer.Exit(1 if failed else 0)


@app.command()
def label(run_id: Annotated[str, typer.Argument(help="Laufordner unter results/runs/")]) -> None:
    """Falsche Antworten ohne automatische Kategorie in analysis/labels.csv zur Handkategorisierung eintragen."""
    from energie_sql_bench.config import load_settings
    from energie_sql_bench.files import read_json
    from energie_sql_bench.taxonomy import export_label_template

    settings = load_settings()
    summary = read_json(settings.path(f"results/runs/{run_id}/summary.json"))
    added = export_label_template(settings.path("analysis/labels.csv"), run_id, summary["items"])
    typer.echo(f"{added} Zeilen zur Kategorisierung (E3 bis E9) in analysis/labels.csv ergänzt")
