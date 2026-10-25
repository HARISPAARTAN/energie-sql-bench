from typer.testing import CliRunner

from energie_sql_bench.cli import app


def test_version() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.1"


def test_guard_check_blocks_delete() -> None:
    result = CliRunner().invoke(app, ["guard-check", "DELETE FROM dw.fact_preis"])
    assert result.exit_code == 1
    assert "BLOCKIERT" in result.stdout


def test_guard_check_allows_select() -> None:
    result = CliRunner().invoke(app, ["guard-check", "SELECT COUNT(*) FROM dw.fact_preis"])
    assert result.exit_code == 0
    assert "dw.fact_preis" in result.stdout
