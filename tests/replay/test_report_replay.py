from pathlib import Path

from energie_sql_bench.config import load_settings
from energie_sql_bench.report import PENDING, build_outputs, stale_outputs

REPO = Path(__file__).resolve().parents[2]
SETTINGS = load_settings(REPO, environ={})


def test_report_is_byte_identical_to_the_committed_files() -> None:
    assert stale_outputs(build_outputs(SETTINGS)) == []


def test_no_model_number_without_a_live_run() -> None:
    outputs = build_outputs(SETTINGS)
    board = outputs[REPO / "reports" / "leaderboard.md"]
    assert board.count(PENDING["de"]) >= len(SETTINGS.report.planned)
    assert "Pipeline-Test (synthetisch, kein Sprachmodell)" in board
    site = outputs[REPO / "site" / "index.html"]
    assert "ausstehend: Live-Lauf" in site and "#0B0F14" in site
