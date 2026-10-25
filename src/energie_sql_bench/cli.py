"""Command line interface `esb`. Commands import their modules lazily so the CLI starts fast."""

from __future__ import annotations

import typer

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
