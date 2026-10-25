"""CLI paths of run and label that end before any provider or database call."""

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from energie_sql_bench.cli import app

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in ("bench", "schema", "semantic", "snapshot"):
        shutil.copytree(REPO / name, tmp_path / name)
    for name in ("config.toml", "pricing.toml", "pyproject.toml"):
        shutil.copy(REPO / name, tmp_path / name)
    monkeypatch.setenv("ESB_ROOT", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return tmp_path


def invoke(*args: str):  # noqa: ANN201
    return CliRunner().invoke(app, ["run", *args])


def test_unknown_variant_is_refused(root: Path) -> None:
    result = invoke("--provider", "synthetic", "--variant", "v9")
    assert result.exit_code == 1 and "unbekannte Variante v9" in result.stdout


def test_model_without_price_is_refused(root: Path) -> None:
    result = invoke("--provider", "anthropic", "--model", "claude-unknown-9")
    assert result.exit_code == 1 and "kein Preis für claude-unknown-9" in result.stdout


def test_existing_run_is_never_overwritten(root: Path) -> None:
    (root / "results" / "runs" / "keep").mkdir(parents=True)
    result = invoke("--provider", "synthetic", "--run-id", "keep")
    assert result.exit_code == 1 and "existiert bereits" in result.stdout


def test_cost_estimate_above_the_ceiling_is_refused(root: Path) -> None:
    result = invoke("--provider", "anthropic", "--max-usd", "0.01", "--run-id", "too-dear")
    assert result.exit_code == 1 and "Kostenschätzung" in result.stdout and "--max-usd" in result.stdout
    assert not (root / "results" / "runs" / "too-dear").exists()


def test_missing_api_key_stops_before_the_database(root: Path) -> None:
    result = invoke("--provider", "anthropic", "--run-id", "no-key")
    assert result.exit_code == 1 and "ANTHROPIC_API_KEY fehlt" in result.stdout
    assert not (root / "results" / "runs" / "no-key").exists()


def test_label_appends_rows_for_unlabelled_errors(root: Path) -> None:
    run = root / "results" / "runs" / "r1"
    run.mkdir(parents=True)
    items = [
        {"item_id": "q001-de", "repeat": 0, "labels": ["E?"]},
        {"item_id": "q002-de", "repeat": 0, "labels": ["E2"]},
    ]
    (run / "summary.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    first = CliRunner().invoke(app, ["label", "r1"])
    assert first.exit_code == 0 and first.stdout.startswith("1 Zeilen")
    text = (root / "analysis" / "labels.csv").read_text(encoding="utf-8")
    assert text == "run_id,item_id,repeat,label,note\nr1,q001-de,0,,\n"
    assert CliRunner().invoke(app, ["label", "r1"]).stdout.startswith("0 Zeilen")
