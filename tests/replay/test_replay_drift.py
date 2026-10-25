"""The replay must notice a changed summary, a changed response and a missing result set."""

import gzip
import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from energie_sql_bench.cli import app
from energie_sql_bench.config import load_settings
from energie_sql_bench.llm.base import ReplayMiss
from energie_sql_bench.runner import replay_run

REPO = Path(__file__).resolve().parents[2]
RUN = "synthetic-v4-test"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for name in ("bench", "schema", "semantic", "snapshot"):
        shutil.copytree(REPO / name, tmp_path / name)
    for name in ("config.toml", "pricing.toml", "pyproject.toml"):
        shutil.copy(REPO / name, tmp_path / name)
    shutil.copytree(REPO / "results" / "runs" / RUN, tmp_path / "results" / "runs" / RUN)
    return tmp_path


def test_untouched_copy_replays_clean(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ESB_ROOT", str(root))
    result = CliRunner().invoke(app, ["replay", RUN])
    assert result.exit_code == 0 and f"OK {RUN}" in result.stdout


def test_changed_summary_is_reported(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = root / "results" / "runs" / RUN / "summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary["ex"]["correct"] += 1
    path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("ESB_ROOT", str(root))
    result = CliRunner().invoke(app, ["replay", RUN])
    assert result.exit_code == 1 and f"ABWEICHUNG {RUN}" in result.stdout


def test_changed_response_changes_the_recomputed_summary(root: Path) -> None:
    path = root / "results" / "runs" / RUN / "responses.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    target = next(
        r for r in rows if r["text"] and r["text"].startswith("```sql") and r["meta"]["behaviour"] <= 5
    )
    target["text"] = "NICHT_BEANTWORTBAR"
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8"
    )
    recomputed, stored = replay_run(load_settings(root, environ={}), RUN)
    assert recomputed["ex"]["correct"] == stored["ex"]["correct"] - 1


def test_missing_result_set_fails_loudly(root: Path) -> None:
    path = root / "results" / "runs" / RUN / "predictions.jsonl.gz"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(lines[1:]) + "\n")
    with pytest.raises(ReplayMiss):
        replay_run(load_settings(root, environ={}), RUN)


def test_replay_without_argument_exits_with_two(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ESB_ROOT", str(REPO))
    assert CliRunner().invoke(app, ["replay"]).exit_code == 2
