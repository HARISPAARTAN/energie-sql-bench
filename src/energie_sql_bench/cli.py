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
