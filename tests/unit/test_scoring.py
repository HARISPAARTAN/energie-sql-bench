from decimal import Decimal

import pytest

from energie_sql_bench.config import CompareSettings, ModelPrice
from energie_sql_bench.files import dump_json
from energie_sql_bench.gold import GoldEntry
from energie_sql_bench.questions import Question
from energie_sql_bench.records import AttemptRecord, Outcome, Usage
from energie_sql_bench.resultset import ResultSet
from energie_sql_bench.scoring import (
    BOOTSTRAP_SEED,
    METHODOLOGY_NOTE,
    bootstrap_interval,
    cost_usd,
    majority_by_item,
    majority_by_question,
    mcnemar_exact,
    paired_discordant,
    percentile,
    score_item,
    summarize,
    wilson,
)
from energie_sql_bench.taxonomy import auto_labels

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
GOLD_TWO_COLUMNS = GoldEntry(
    "q001", "rows", ResultSet(["a", "b"], ["decimal", "decimal"], [[Decimal("1"), Decimal("2")]]), "s", "d"
)


def rs(value: object) -> ResultSet:
    return ResultSet(["x"], ["decimal"], [[value]])


def test_wilson() -> None:
    lo, hi = wilson(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-3) and hi == pytest.approx(0.9433, abs=1e-3)
    assert wilson(0, 0) == (0.0, 1.0)
    # closed form from the quadratic (p - x)^2 = z^2 x (1 - x) / n
    assert wilson(5, 10) == pytest.approx((0.236593090512564, 0.763406909487436), abs=1e-9)


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
    assert score_item(ROWS_Q, GOLD, "ok", rs(Decimal("1.5")), CMP) == (True, True, 0, "ok")
    assert score_item(ROWS_Q, GOLD, "ok", rs(Decimal("2")), CMP) == (
        False,
        False,
        0,
        "keine passende Spalte für Gold-Spalte a",
    )
    assert score_item(ROWS_Q, GOLD, "abstain", None, CMP) == (False, False, 0, "Enthaltung statt Antwort")
    assert score_item(ROWS_Q, GOLD, "db_error", None, CMP) == (False, False, 0, "Status db_error")
    truncated = ResultSet(["x"], ["decimal"], [[Decimal("1.5")]], truncated=True)
    assert score_item(ROWS_Q, GOLD, "truncated", truncated, CMP) == (
        False,
        False,
        0,
        "Vorhersage abgeschnitten (Zeilenlimit)",
    )


def test_score_rows_item_lenient_and_strict_differ() -> None:
    wide = ResultSet(["x", "y"], ["decimal", "decimal"], [[Decimal("1.5"), Decimal("9")]])
    assert score_item(ROWS_Q, GOLD, "ok", wide, CMP) == (True, False, 1, "ok")
    assert score_item(ROWS_Q, GOLD_TWO_COLUMNS, "ok", rs(Decimal("1")), CMP) == (
        False,
        False,
        0,
        "zu wenige Spalten (1 statt 2)",
    )


def test_e10_label_comes_from_the_real_comparator_message() -> None:
    correct, _, _, reason = score_item(ROWS_Q, GOLD_TWO_COLUMNS, "ok", rs(Decimal("1")), CMP)
    assert auto_labels("rows", "ok", None, correct, reason) == ("E10",)
    correct, _, _, reason = score_item(ROWS_Q, GOLD, "ok", rs(Decimal("2")), CMP)
    assert auto_labels("rows", "ok", None, correct, reason) == ("E?",)


def test_score_abstain_item() -> None:
    assert score_item(ABSTAIN_Q, None, "abstain", None, CMP) == (True, True, 0, "Enthaltung")
    assert score_item(ABSTAIN_Q, None, "ok", rs(None), CMP) == (True, True, 0, "leeres Ergebnis")
    assert score_item(ABSTAIN_Q, None, "ok", rs(Decimal("5")), CMP) == (
        False,
        False,
        0,
        "beantwortet statt enthalten",
    )
    assert score_item(ABSTAIN_Q, None, "db_error", None, CMP) == (False, False, 0, "Status db_error")


def attempt(
    n: int, status: str, usage: Usage | None = None, llm_ms: float = 10.0, db_ms: float = 2.0
) -> AttemptRecord:
    return AttemptRecord(
        n, "h", status, "SELECT 1", "s", None, None, usage or Usage(100, 0, 0, 10), llm_ms, db_ms
    )


def outcome(
    qid: str,
    lang: str,
    repeat: int,
    correct: bool,
    status: str = "ok",
    tier: str = "T1",
    *,
    strict: bool | None = None,
    extra: int = 0,
    attempts: tuple[AttemptRecord, ...] | None = None,
    labels: tuple[str, ...] | None = None,
    cost: float = 0.001,
) -> Outcome:
    return Outcome(
        f"{qid}-{lang}",
        qid,
        lang,
        tier,
        "abstain" if tier == "A" else "rows",
        repeat,
        attempts if attempts is not None else (attempt(0, status),),
        status,
        correct,
        correct if strict is None else strict,
        extra,
        "ok" if correct else "x",
        labels if labels is not None else (() if correct else ("E?",)),
        cost,
    )


def mixed_run() -> list[Outcome]:
    """Ten items chosen so that strict differs from lenient and every summary field has its own value."""
    return [
        outcome("q001", "de", 0, True, cost=0.001, attempts=(attempt(0, "ok", llm_ms=10.0, db_ms=2.0),)),
        outcome(
            "q001",
            "en",
            0,
            True,
            strict=False,
            extra=1,
            cost=0.002,
            attempts=(attempt(0, "ok", Usage(100, 50, 25, 10), llm_ms=20.0, db_ms=4.0),),
        ),
        outcome(
            "q002",
            "de",
            0,
            True,
            tier="T2",
            cost=0.003,
            attempts=(
                attempt(0, "blocked", Usage(200, 0, 0, 20), llm_ms=30.0, db_ms=0.0),
                attempt(1, "ok", Usage(200, 0, 0, 20), llm_ms=40.0, db_ms=6.0),
            ),
        ),
        outcome(
            "q002",
            "en",
            0,
            False,
            status="db_error",
            tier="T2",
            labels=("E2",),
            cost=0.004,
            attempts=(
                attempt(0, "db_error", llm_ms=50.0, db_ms=1.0),
                attempt(1, "db_error", llm_ms=60.0, db_ms=1.0),
            ),
        ),
        outcome(
            "q003",
            "de",
            0,
            False,
            tier="T3",
            cost=0.005,
            attempts=(attempt(0, "ok", llm_ms=70.0, db_ms=8.0),),
        ),
        outcome(
            "q003",
            "en",
            0,
            False,
            status="no_sql",
            tier="T3",
            labels=("E1",),
            cost=0.006,
            attempts=(attempt(0, "no_sql", llm_ms=80.0, db_ms=0.0),),
        ),
        outcome(
            "q004",
            "de",
            0,
            False,
            status="abstain",
            labels=("E12",),
            cost=0.007,
            attempts=(attempt(0, "abstain", llm_ms=90.0, db_ms=0.0),),
        ),
        outcome(
            "q004",
            "en",
            0,
            False,
            status="abstain",
            labels=("E12",),
            cost=0.010,
            attempts=(attempt(0, "abstain", llm_ms=120.0, db_ms=0.0),),
        ),
        outcome(
            "q010",
            "de",
            0,
            True,
            status="abstain",
            tier="A",
            cost=0.008,
            attempts=(attempt(0, "abstain", llm_ms=100.0, db_ms=0.0),),
        ),
        outcome(
            "q010",
            "en",
            0,
            False,
            status="ok",
            tier="A",
            labels=("E12",),
            cost=0.009,
            attempts=(attempt(0, "ok", llm_ms=110.0, db_ms=10.0),),
        ),
    ]


def test_summarize_every_field_of_a_mixed_run() -> None:
    s = summarize(mixed_run(), repeats=1, eur_usd=1.25)
    # Correct: q001-de, q001-en, q002-de (after a repair), q010-de = 4 of 10; strict: q001-en has an extra column = 3.
    assert s["ex"]["correct"] == 4 and s["ex"]["n"] == 10 and s["ex"]["items"] == 10
    assert (s["ex"]["mean"], s["ex"]["min"], s["ex"]["max"], s["ex"]["per_repeat"]) == (0.4, 0.4, 0.4, [0.4])
    # Question-level bootstrap over the 5 intents (seeded, so the values are fixed); not Wilson over 10 items.
    assert s["ex"]["ci95"] == [0.1, 0.7]
    assert s["ex"]["interval"] == "bootstrap" and s["ex"]["questions"] == 5
    assert s["ex_strict"]["correct"] == 3 and s["ex_strict"]["n"] == 10
    assert (s["ex_strict"]["mean"], s["ex_strict"]["per_repeat"]) == (0.3, [0.3])
    assert s["ex_strict"]["ci95"] == [0.1, 0.5]
    assert s["by_lang"] == {"de": {"correct": 3, "ex": 0.6, "n": 5}, "en": {"correct": 1, "ex": 0.2, "n": 5}}
    assert s["by_tier"] == {
        "A": {"correct": 1, "ex": 0.5, "n": 2},
        "T1": {"correct": 2, "ex": 0.5, "n": 4},
        "T2": {"correct": 1, "ex": 0.5, "n": 2},
        "T3": {"correct": 0, "ex": 0.0, "n": 2},
    }
    assert s["de_vs_en"] == {"de_only": 2, "en_only": 0, "p_value": 0.5}
    # expected abstentions: q010 de and en; right: q010-de; predicted abstentions: q004 de, q004 en, q010-de
    assert s["abstention"] == {
        "correct": 1,
        "expected": 2,
        "precision": 0.333333,
        "predicted": 3,
        "recall": 0.5,
    }
    assert s["blocked_attempts"] == 1 and s["repair_attempts"] == 2 and s["repaired_correct"] == 1
    # rows items: 8; final status ok or truncated: q001 de, q001 en, q002-de, q003-de = 4
    assert s["validity"] == {"n": 8, "rate": 0.5, "valid": 4}
    assert s["cost"] == {"eur": 0.044, "usd": 0.055, "usd_per_correct": 0.01375}
    assert s["tokens"] == {
        "cache_creation_tokens": 50,
        "cache_read_tokens": 25,
        "input_tokens": 1400,
        "output_tokens": 140,
    }
    # twelve attempts, llm_ms 10 ... 120: nearest rank 6 and 12; executed attempts have db_ms 1 1 2 4 6 8 10
    assert s["latency_ms"] == {"db_p50": 4.0, "db_p95": 10.0, "llm_p50": 60.0, "llm_p95": 120.0}
    assert s["labels"] == {"E1": 1, "E12": 3, "E2": 1, "E?": 1}
    assert s["prompt_tokens_max"] == 200  # the repaired q002-de attempts: 200 fresh input tokens each
    assert s["n_items"] == 10 and s["repeats"] == 1 and s["complete"] is True and s["aborted_reason"] is None
    assert s["summary_version"] == 3 and len(s["items"]) == 10
    assert s["items"][1]["strict"] is False and s["items"][1]["extra_columns"] == 1


def test_summarize_aborted_run_keeps_reason_and_counts_distinct_items() -> None:
    outs = [outcome("q001", "de", 0, True), outcome("q001", "de", 1, False), outcome("q002", "de", 0, True)]
    s = summarize(outs, repeats=2, eur_usd=1.0, complete=False, aborted_reason="Kostenobergrenze")
    assert s["complete"] is False and s["aborted_reason"] == "Kostenobergrenze"
    assert s["n_items"] == 2  # distinct items; len // repeats would give 1 for the partial repeat


def test_summary_is_json_stable() -> None:
    outs = mixed_run()
    assert dump_json(summarize(outs, 1, 1.1)) == dump_json(summarize(list(outs), 1, 1.1))


def repeated(patterns: dict[tuple[str, str], list[bool]]) -> list[Outcome]:
    """Outcomes for items given by (question, lang) with one correctness flag per repeat."""
    return [outcome(q, lang, r, flags[r]) for (q, lang), flags in patterns.items() for r in range(len(flags))]


def test_bootstrap_helper_is_seeded() -> None:
    assert bootstrap_interval([]) == (0.0, 1.0)
    clusters = [(1.0, 1)] * 5 + [(0.0, 1)] * 5
    assert bootstrap_interval(clusters) == bootstrap_interval(clusters)
    lo, hi = bootstrap_interval(clusters)
    assert 0.1 < lo < 0.3 and 0.7 < hi < 0.9


def test_bootstrap_depends_on_the_seed() -> None:
    uneven = [(1.0, 1), (2.0, 2), (0.0, 2), (1.0, 3), (3.0, 3), (0.5, 1), (0.0, 1)]
    assert bootstrap_interval(uneven) == bootstrap_interval(uneven)
    assert bootstrap_interval(uneven, seed=BOOTSTRAP_SEED + 1) != bootstrap_interval(uneven)


def test_majority_and_pairing() -> None:
    majority = majority_by_item(
        [
            ("a", True),
            ("a", True),
            ("a", False),
            ("b", True),
            ("b", False),
            ("c", False),
            ("c", False),
            ("c", True),
        ]
    )
    assert majority == {"a": True, "b": False, "c": False}  # a tie (b) is not correct
    assert paired_discordant({"a": True, "b": False, "c": True}, {"a": False, "b": False, "d": True}) == (
        2,
        1,
        0,
    )


def test_repeats_do_not_shrink_the_interval() -> None:
    # Ten questions, perfectly correlated repeats: five always right, five always wrong. Counting 30 independent
    # observations gives the Wilson interval of 15/30 (width about 0.34); the questions are the real sample.
    patterns = {(f"q{n:03d}", "de"): [n <= 5] * 3 for n in range(1, 11)}
    s = summarize(repeated(patterns), repeats=3, eur_usd=1.0)
    ex = s["ex"]
    assert (ex["correct"], ex["n"], ex["items"], ex["mean"]) == (15, 30, 10, 0.5)
    assert ex["interval"] == "bootstrap" and ex["per_repeat"] == [0.5, 0.5, 0.5]
    old_lo, old_hi = wilson(15, 30)
    lo, hi = ex["ci95"]
    assert (hi - lo) > 1.5 * (old_hi - old_lo)
    assert lo < old_lo and hi > old_hi
    assert 0.15 < lo < 0.35 and 0.65 < hi < 0.85  # about 0.5 +- 1.96 * sqrt(0.25 / 10)
    assert s["n_items"] == 10 and s["repeats"] == 3
    assert summarize(repeated(patterns), repeats=3, eur_usd=1.0)["ex"]["ci95"] == ex["ci95"]


def test_repeats_mean_min_max_and_item_level_aggregation() -> None:
    # q001 right in repeats 0 and 1; q002 right in repeat 0 only; q003 never right
    patterns = {
        ("q001", "de"): [True, True, False],
        ("q002", "de"): [True, False, False],
        ("q003", "de"): [False] * 3,
    }
    ex = summarize(repeated(patterns), repeats=3, eur_usd=1.0)["ex"]
    assert ex["per_repeat"] == [0.666667, 0.333333, 0.0]
    assert (ex["min"], ex["max"], ex["mean"]) == (0.0, 0.666667, 0.333333)
    assert (ex["correct"], ex["n"], ex["items"]) == (3, 9, 3)


def test_de_vs_en_uses_the_per_item_majority_not_every_repeat() -> None:
    # German right in all repeats and English wrong in all, for three questions, plus two questions whose majorities
    # agree. Counting every repeat as a pair gives de_only = 9 (p = 0.0039); the items give 3 (p = 0.25).
    patterns: dict[tuple[str, str], list[bool]] = {}
    for q in ("q001", "q002", "q003"):
        patterns[(q, "de")] = [True, True, True]
        patterns[(q, "en")] = [False, False, False]
    patterns[("q004", "de")] = [True, True, False]  # majority right
    patterns[("q004", "en")] = [True, False, True]  # majority right
    patterns[("q005", "de")] = [True, False, False]  # majority wrong
    patterns[("q005", "en")] = [False, False, True]  # majority wrong
    assert summarize(repeated(patterns), repeats=3, eur_usd=1.0)["de_vs_en"] == {
        "de_only": 3,
        "en_only": 0,
        "p_value": 0.25,
    }


def test_de_vs_en_majority_flips_a_single_repeat_disagreement() -> None:
    patterns = {("q001", "de"): [True, True, False], ("q001", "en"): [False, False, True]}
    assert summarize(repeated(patterns), repeats=3, eur_usd=1.0)["de_vs_en"] == {
        "de_only": 1,
        "en_only": 0,
        "p_value": 1.0,
    }


def test_methodology_note_is_available_in_both_languages() -> None:
    assert set(METHODOLOGY_NOTE) == {"de", "en"}
    assert "Bootstrap" in METHODOLOGY_NOTE["de"] and "bootstrap" in METHODOLOGY_NOTE["en"]


def test_single_repeat_interval_is_clustered_by_intent_not_wilson_over_items() -> None:
    # Ten intents, German and English always agree: five intents right in both languages, five wrong in both.
    # Wilson over 20 items (width about 0.40) would treat the 20 items as independent; the sample is 10 intents.
    patterns: dict[tuple[str, str], list[bool]] = {}
    for n in range(1, 11):
        for lang in ("de", "en"):
            patterns[(f"q{n:03d}", lang)] = [n <= 5]
    ex = summarize(repeated(patterns), repeats=1, eur_usd=1.0)["ex"]
    assert (ex["correct"], ex["n"], ex["items"], ex["questions"], ex["interval"]) == (
        10,
        20,
        20,
        10,
        "bootstrap",
    )
    wilson_lo, wilson_hi = wilson(10, 20)
    lo, hi = ex["ci95"]
    assert (hi - lo) > 1.3 * (wilson_hi - wilson_lo)
    # The same outcomes with independent languages (5 right in German only, 5 in English only) give a narrower
    # interval, because every intent then carries one right and one wrong item.
    mixed = {(f"q{n:03d}", lang): [(lang == "de") == (n <= 5)] for n in range(1, 11) for lang in ("de", "en")}
    mlo, mhi = summarize(repeated(mixed), repeats=1, eur_usd=1.0)["ex"]["ci95"]
    assert (mhi - mlo) < (hi - lo)


def test_majority_by_question_needs_every_language_item_correct() -> None:
    rows = [
        ("q1", "q1-de", True),
        ("q1", "q1-en", True),
        ("q2", "q2-de", True),
        ("q2", "q2-en", False),
        ("q3", "q3-de", False),
        ("q3", "q3-en", False),
        # q4: both items right in two of three repeats, so both are majority-correct
        ("q4", "q4-de", True),
        ("q4", "q4-de", True),
        ("q4", "q4-de", False),
        ("q4", "q4-en", True),
        ("q4", "q4-en", False),
        ("q4", "q4-en", True),
    ]
    assert majority_by_question(rows) == {"q1": True, "q2": False, "q3": False, "q4": True}
    assert majority_by_question([]) == {}
