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


def test_gold_provenance_is_disclosed_and_no_single_author_claim_remains() -> None:
    outputs = build_outputs(SETTINGS)
    assert "Sprachmodell entworfen" in outputs[REPO / "site" / "index.html"]
    assert "drafted by a language model" in outputs[REPO / "site" / "en.html"]
    for name, heading in (
        ("README.md", "## Herkunft des Goldstandards"),
        ("README.en.md", "## Provenance of the gold set"),
    ):
        assert heading in (REPO / name).read_text(encoding="utf-8")
    for name in ("README.md", "README.en.md", "docs/methodology.md", "LICENSE-DATA.md"):
        text = (REPO / name).read_text(encoding="utf-8")
        assert "von einer Person" not in text and "written by one person" not in text
        assert "unabhängige Gegenprobe" not in text and "independent check query" not in text
