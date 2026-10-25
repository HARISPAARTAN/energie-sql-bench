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
