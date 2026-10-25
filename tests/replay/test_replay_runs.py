from pathlib import Path

import pytest

from energie_sql_bench.config import load_settings
from energie_sql_bench.files import dump_json
from energie_sql_bench.runner import list_runs, replay_run

REPO = Path(__file__).resolve().parents[2]
SETTINGS = load_settings(REPO, environ={})
RUNS = list_runs(SETTINGS)


def test_synthetic_runs_are_committed() -> None:
    assert {"synthetic-v4-test", "synthetic-v4-test-sc"} <= set(RUNS)


@pytest.mark.parametrize("run_id", RUNS)
def test_replay_reproduces_summary(run_id: str) -> None:
    recomputed, stored = replay_run(SETTINGS, run_id)
    assert dump_json(recomputed) == dump_json(stored)


def test_synthetic_expectations() -> None:
    single, _ = replay_run(SETTINGS, "synthetic-v4-test")
    repaired, _ = replay_run(SETTINGS, "synthetic-v4-test-sc")
    assert (single["ex"]["correct"], single["ex"]["n"]) == (82, 120)
    assert (repaired["ex"]["correct"], repaired["ex"]["n"]) == (111, 120)
    assert repaired["repaired_correct"] == 29
