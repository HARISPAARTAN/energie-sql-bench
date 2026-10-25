from pathlib import Path

from energie_sql_bench.config import PlannedConfig, load_settings
from energie_sql_bench.report import (
    HEADLINE_END,
    HEADLINE_START,
    PENDING,
    Eligibility,
    RunView,
    comparison_rows,
    excluded_runs,
    fmt_num,
    fmt_pct,
    headline_markdown,
    ineligible_reason,
    label_sort_key,
    leaderboard_rows,
    replace_headline,
    select_runs,
)

REPO = Path(__file__).resolve().parents[2]
SETTINGS = load_settings(REPO, environ={})
HAIKU_V1 = "anthropic|claude-haiku-5-5|v1|0"
HAIKU_V4 = "anthropic|claude-haiku-5-5|v4|0"


def elig(n_items: int = 2) -> Eligibility:
    return Eligibility(snapshot="snap1", prompt_version="1", n_items=n_items)


def summary(correct: list[bool], complete: bool = True) -> dict:
    n = len(correct)
    k = sum(correct)
    return {
        "abstention": {"precision": 1.0, "recall": 0.5},
        "blocked_attempts": 1,
        "complete": complete,
        "cost": {"usd": 0.01, "usd_per_correct": 0.002, "eur": 0.0086},
        "ex": {
            "ci95": [0.2, 0.9],
            "correct": k,
            "max": k / n,
            "mean": k / n,
            "min": k / n,
            "n": n,
            "per_repeat": [k / n],
        },
        "ex_strict": {
            "ci95": [0.2, 0.9],
            "correct": k,
            "max": k / n,
            "mean": k / n,
            "min": k / n,
            "n": n,
            "per_repeat": [k / n],
        },
        "items": [
            {"item_id": f"q{i:03d}-de", "repeat": 0, "correct": c, "labels": [] if c else ["E?"]}
            for i, c in enumerate(correct, 1)
        ],
        "labels": {"E?": n - k} if n - k else {},
        "n_items": n,
        "latency_ms": {"db_p50": 12.0, "db_p95": 40.0, "llm_p50": 900.0, "llm_p95": 2100.0},
        "repair_attempts": 0,
        "repeats": 1,
        "tokens": {
            "cache_creation_tokens": 0,
            "cache_read_tokens": 1000,
            "input_tokens": 200,
            "output_tokens": 50,
        },
        "validity": {"n": n, "rate": 1.0, "valid": n},
    }


def run(
    run_id: str,
    key: str,
    correct: list[bool],
    created: str = "2026-11-01",
    synthetic: bool = False,
    split: str = "test",
    **overrides,
) -> RunView:
    p = PlannedConfig.parse(key)
    return RunView(
        run_id,
        key,
        p.provider,
        p.model,
        p.variant,
        p.self_correct,
        split,
        synthetic,
        created,
        summary(correct),
        **{"snapshot": "snap1", "prompt_version": "1", "langs": ("de", "en"), "limit": None, **overrides},
    )


def test_number_formats() -> None:
    assert fmt_num(1234.5, 1, "de") == "1.234,5"
    assert fmt_num(1234.5, 1, "en") == "1,234.5"
    assert fmt_pct(0.68333, "de") == "68,3 %"
    assert fmt_pct(None, "en") == "–"


def test_label_order() -> None:
    assert sorted(["E?", "E12", "E2", "E1"], key=label_sort_key) == ["E1", "E2", "E12", "E?"]


def test_pending_when_no_real_run() -> None:
    runs = [run("synthetic-v4-test", "synthetic|synthetic-gold-v1|v4|0", [True, False], synthetic=True)]
    chosen = select_runs(runs, SETTINGS.report.planned, elig())
    assert len(chosen) == len(SETTINGS.report.planned) and all(r is None for _, r in chosen)
    rows = leaderboard_rows(chosen, SETTINGS, "de")
    assert all(r["pending"] and r["ex"] == PENDING["de"] for r in rows)


def test_newest_complete_test_run_wins() -> None:
    old = run("haiku-old", HAIKU_V4, [True, False], created="2026-11-01")
    new = run("haiku-new", HAIKU_V4, [True, True], created="2026-11-02")
    dev = run("haiku-dev", HAIKU_V4, [True, True], created="2026-11-03", split="dev")
    chosen = dict(select_runs([old, new, dev], SETTINGS.report.planned, elig()))
    assert chosen[HAIKU_V4].run_id == "haiku-new"
    row = next(r for r in leaderboard_rows(list(chosen.items()), SETTINGS, "en") if r["key"] == HAIKU_V4)
    assert row["ex"] == "100.0 % (20.0 %–90.0 %)" and row["n"] == "2/2"


def test_comparison_uses_paired_items() -> None:
    a = run("a", HAIKU_V1, [True, False, False, False])
    b = run("b", HAIKU_V4, [True, True, True, False])
    rows = comparison_rows(select_runs([a, b], SETTINGS.report.planned, elig(4)), SETTINGS, "en")
    first = rows[0]
    assert (first["pairs"], first["a_only"], first["b_only"]) == ("4", "0", "2")
    assert first["p"] == "0.5000"
    assert rows[1]["p"] == PENDING["en"]


def test_headline_lists_v4_models_and_marks_synthetic() -> None:
    chosen = select_runs([], SETTINGS.report.planned, elig())
    rows = leaderboard_rows(chosen, SETTINGS, "de")
    synthetic = [{"run_id": "synthetic-v4-test", "mode": "Einzelversuch", "ex": "68,3 % (82/120)"}]
    text = headline_markdown(rows, synthetic, "de")
    assert text.count(PENDING["de"]) == 4
    assert "Pipeline-Test (synthetisch, kein Sprachmodell): `synthetic-v4-test`" in text


def test_replace_headline_keeps_the_rest() -> None:
    text = f"A\n{HEADLINE_START}\nalt\n{HEADLINE_END}\nB\n"
    assert replace_headline(text, "neu") == f"A\n{HEADLINE_START}\nneu\n{HEADLINE_END}\nB\n"


def repeated(run_id: str, key: str, per_repeat: list[list[bool]]) -> RunView:
    """A run with several repeats: per_repeat[r][i] is the outcome of item i in repeat r."""
    base = run(run_id, key, per_repeat[0])
    items = [
        {"item_id": f"q{i:03d}-de", "repeat": r, "correct": c, "labels": []}
        for r, outcomes in enumerate(per_repeat)
        for i, c in enumerate(outcomes, 1)
    ]
    return RunView(
        base.run_id,
        key,
        base.provider,
        base.model,
        base.variant,
        base.self_correct,
        "test",
        False,
        base.created,
        {**base.summary, "items": items, "repeats": len(per_repeat)},
        base.snapshot,
        base.prompt_version,
        base.langs,
        base.limit,
    )


def test_comparison_pairs_items_by_majority_never_item_and_repeat() -> None:
    # 4 items x 3 repeats. A: item 1 and 2 correct in 2 of 3 repeats (majority), items 3 and 4 in 1 of 3.
    a = repeated(
        "a", HAIKU_V1, [[True, True, True, False], [True, True, False, True], [False, False, False, False]]
    )
    # B: item 1 never, items 2 to 4 always.
    b = repeated("b", HAIKU_V4, [[False, True, True, True]] * 3)
    row = comparison_rows(select_runs([a, b], SETTINGS.report.planned, elig(4)), SETTINGS, "en")[0]
    # majority A: [T, T, F, F]; majority B: [F, T, T, T] -> 4 pairs (not 12), A only: item 1, B only: items 3, 4
    assert (row["pairs"], row["a_only"], row["b_only"]) == ("4", "1", "2")
    assert row["p"] == "1.0000"


def test_interval_wording_comes_from_the_methodology_note() -> None:
    from energie_sql_bench.report import build_context
    from energie_sql_bench.scoring import METHODOLOGY_NOTE

    for lang in ("de", "en"):
        assert build_context(SETTINGS, lang)["methodology_note"] == METHODOLOGY_NOTE[lang]


def test_a_limit_or_single_language_run_is_never_a_published_row() -> None:
    full = run("full", HAIKU_V4, [True, False], created="2026-11-01")
    smoke = run("smoke", HAIKU_V4, [True, True], created="2026-11-02", limit=10)
    german = run("german", HAIKU_V4, [True, True], created="2026-11-03", langs=("de",))
    chosen = dict(select_runs([full, smoke, german], SETTINGS.report.planned, elig()))
    assert chosen[HAIKU_V4].run_id == "full"
    reasons = {e["run_id"]: e["reason"] for e in excluded_runs([full, smoke, german], elig())}
    assert reasons == {"smoke": "--limit 10: nur ein Teil der Items", "german": "Sprachen de statt de+en"}


def test_every_mismatch_with_the_planned_configuration_is_refused_with_a_reason() -> None:
    expected = elig()
    assert ineligible_reason(run("ok", HAIKU_V4, [True, False]), expected) is None
    cases = {
        "snapshot": ({"snapshot": "other"}, "Snapshot other statt snap1"),
        "prompt": ({"prompt_version": "2"}, "Prompt-Version 2 statt 1"),
        "unknown snapshot": ({"snapshot": None}, "Snapshot None statt snap1"),
        "unknown languages": ({"langs": None}, "Sprachen unbekannt statt de+en"),
        "english only": ({"langs": ("en",)}, "Sprachen en statt de+en"),
    }
    for name, (overrides, reason) in cases.items():
        assert ineligible_reason(run(name, HAIKU_V4, [True, False], **overrides), expected) == reason
    assert ineligible_reason(run("n", HAIKU_V4, [True, False]), elig(120)) == "2 Items statt 120"
    assert (
        ineligible_reason(run("dev", HAIKU_V4, [True, False], split="dev"), expected)
        == "Split dev statt test"
    )
    incomplete = run("inc", HAIKU_V4, [True, False])
    incomplete.summary["complete"] = False
    assert ineligible_reason(incomplete, expected) == "unvollständiger Lauf"


def test_synthetic_runs_are_neither_published_nor_listed_as_excluded() -> None:
    synthetic = run("syn", "synthetic|synthetic-gold-v1|v4|0", [True, False], synthetic=True, limit=3)
    assert excluded_runs([synthetic], elig()) == []


def test_committed_runs_match_the_current_eligibility() -> None:
    from energie_sql_bench.report import eligibility_for

    expected = eligibility_for(SETTINGS)
    assert expected.n_items == 120 and expected.prompt_version == "1"
    from energie_sql_bench.report import load_runs

    assert all(ineligible_reason(r, expected) is None for r in load_runs(SETTINGS))


def language_run(run_id: str, key: str, outcomes: dict[str, tuple[bool, bool]]) -> RunView:
    """outcomes[question] = (german correct, english correct)."""
    items = [
        {"item_id": f"{q}-{lang}", "question_id": q, "repeat": 0, "correct": c, "labels": []}
        for q, pair in outcomes.items()
        for lang, c in zip(("de", "en"), pair, strict=True)
    ]
    base = run(run_id, key, [True] * len(items))
    return RunView(
        base.run_id,
        key,
        base.provider,
        base.model,
        base.variant,
        base.self_correct,
        "test",
        False,
        base.created,
        {**base.summary, "items": items},
        base.snapshot,
        base.prompt_version,
        base.langs,
        base.limit,
    )


def test_mcnemar_pairs_intents_not_language_items() -> None:
    # A is right in both languages on q1 to q4; B fails both languages on q1 and q2, and one language on q3.
    a = language_run("a", HAIKU_V1, {f"q{i}": (True, True) for i in range(1, 5)})
    b = language_run(
        "b", HAIKU_V4, {"q1": (False, False), "q2": (False, False), "q3": (True, False), "q4": (True, True)}
    )
    row = comparison_rows(select_runs([a, b], SETTINGS.report.planned, elig(8)), SETTINGS, "en")[0]
    # 4 intents (not 8 items); a intent is right only when both languages are: B is right on q4 only.
    assert (row["pairs"], row["a_only"], row["b_only"]) == ("4", "3", "0")
    assert row["p"] == "0.2500"
