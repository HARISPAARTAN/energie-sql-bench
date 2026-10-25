from decimal import Decimal
from pathlib import Path

import pytest

from energie_sql_bench.config import CompareSettings, ModelPrice
from energie_sql_bench.gold import GoldEntry
from energie_sql_bench.questions import Question
from energie_sql_bench.records import AttemptRecord, Outcome, Usage
from energie_sql_bench.resultset import ResultSet
from energie_sql_bench.scoring import cost_usd, mcnemar_exact, percentile, score_item, summarize, wilson

CMP = CompareSettings(1e-4, 0.005)
HAIKU = ModelPrice("anthropic", 0.10, 0.125, 0.01, 0.50, "x", "2026-10-25")
SONNET = ModelPrice("anthropic", 2.00, 2.50, 0.20, 10.00, "x", "2026-10-25")
ROWS_Q = Question.model_validate(
    {
        "id": "q001",
        "split": "test",
        "tier": "T1",
        "de": "Preis?",
        "en": "Price?",
        "expect": "rows",
        "gold_sql": "SELECT 1",
        "check_sql": "SELECT 1 AS a",
        "tables": [],
        "notes": "n",
    }
)
ABSTAIN_Q = Question.model_validate(
    {
        "id": "q010",
        "split": "test",
        "tier": "A",
        "de": "Redispatch?",
        "en": "Redispatch?!",
        "expect": "abstain",
        "notes": "n",
    }
)
GOLD = GoldEntry("q001", "rows", ResultSet(["a"], ["decimal"], [[Decimal("1.5")]]), "s", "d")


def rs(value: object) -> ResultSet:
    return ResultSet(["x"], ["decimal"], [[value]])


def test_wilson() -> None:
    lo, hi = wilson(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-3) and hi == pytest.approx(0.9433, abs=1e-3)
    assert wilson(0, 0) == (0.0, 1.0)


def test_mcnemar() -> None:
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(1, 9) == pytest.approx(0.021484375)
    assert mcnemar_exact(5, 5) == 1.0


def test_percentile_nearest_rank() -> None:
    assert percentile([5, 1, 3, 2, 4], 50) == 3
    assert percentile([5, 1, 3, 2, 4], 95) == 5
    assert percentile([], 50) is None


def test_cost() -> None:
    assert cost_usd(Usage(1_000_000, 0, 0, 0), HAIKU) == pytest.approx(0.10)
    assert cost_usd(Usage(1000, 2000, 3000, 400), SONNET) == pytest.approx(0.0116)


def test_score_rows_item() -> None:
    assert score_item(ROWS_Q, GOLD, "ok", rs(Decimal("1.5")), CMP)[0] is True
    assert score_item(ROWS_Q, GOLD, "ok", rs(Decimal("2")), CMP)[0] is False
    assert score_item(ROWS_Q, GOLD, "abstain", None, CMP) == (False, False, 0, "Enthaltung statt Antwort")
    assert score_item(ROWS_Q, GOLD, "db_error", None, CMP)[0] is False
    truncated = ResultSet(["x"], ["decimal"], [[Decimal("1.5")]], truncated=True)
    assert score_item(ROWS_Q, GOLD, "truncated", truncated, CMP)[0] is False


def test_score_abstain_item() -> None:
    assert score_item(ABSTAIN_Q, None, "abstain", None, CMP)[0] is True
    assert score_item(ABSTAIN_Q, None, "ok", rs(None), CMP)[0] is True
    assert score_item(ABSTAIN_Q, None, "ok", rs(Decimal("5")), CMP)[0] is False
    assert score_item(ABSTAIN_Q, None, "db_error", None, CMP)[0] is False


def outcome(qid: str, lang: str, repeat: int, correct: bool, status: str = "ok", tier: str = "T1") -> Outcome:
    attempt = AttemptRecord(0, "h", status, "SELECT 1", "s", None, None, Usage(100, 0, 0, 10), 10.0, 2.0)
    return Outcome(
        f"{qid}-{lang}",
        qid,
        lang,
        tier,
        "abstain" if tier == "A" else "rows",
        repeat,
        (attempt,),
        status,
        correct,
        correct,
        0,
        "ok" if correct else "x",
        () if correct else ("E?",),
        0.001,
    )


def test_summarize_toy_run() -> None:
    outs = [
        outcome("q001", "de", 0, True),
        outcome("q001", "en", 0, False),
        outcome("q002", "de", 0, True),
        outcome("q002", "en", 0, True),
        outcome("q010", "de", 0, True, status="abstain", tier="A"),
        outcome("q010", "en", 0, False, tier="A"),
    ]
    s = summarize(outs, repeats=1, eur_usd=1.25)
    assert s["n_items"] == 6 and s["repeats"] == 1 and s["complete"] is True
    assert s["ex"]["mean"] == pytest.approx(4 / 6, abs=1e-6)
    assert s["by_lang"]["de"]["correct"] == 3 and s["by_lang"]["en"]["correct"] == 1
    assert s["by_tier"]["A"]["n"] == 2
    assert s["de_vs_en"] == {"de_only": 2, "en_only": 0, "p_value": 0.5}
    assert s["abstention"]["recall"] == 0.5
    assert s["cost"]["usd"] == pytest.approx(0.006)
    assert s["cost"]["eur"] == pytest.approx(0.0048)
    assert s["latency_ms"]["llm_p50"] == 10.0
    assert s["tokens"]["input_tokens"] == 600
    assert s["labels"] == {"E?": 2}
    assert len(s["items"]) == 6


def test_summary_is_json_stable(tmp_path: Path) -> None:
    from energie_sql_bench.files import dump_json

    outs = [outcome("q001", "de", 0, True), outcome("q001", "en", 0, False)]
    assert dump_json(summarize(outs, 1, 1.1)) == dump_json(summarize(list(outs), 1, 1.1))
