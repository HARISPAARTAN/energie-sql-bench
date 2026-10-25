import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from energie_sql_bench.config import CompareSettings, ModelPrice, SnapshotSettings, VariantSpec, load_settings
from energie_sql_bench.execute import ExecResult
from energie_sql_bench.gold import GoldEntry
from energie_sql_bench.llm.base import Completion, ProviderError, ReplayMiss, Request
from energie_sql_bench.llm.recorder import read_run, write_run
from energie_sql_bench.llm.replay import RecordedExecutor, ReplayProvider
from energie_sql_bench.prompts import PromptContext
from energie_sql_bench.questions import Question
from energie_sql_bench.records import Usage
from energie_sql_bench.resultset import ResultSet
from energie_sql_bench.runner import (
    BenchContext,
    RunSpec,
    default_run_id,
    estimate_cost,
    execute_run,
    prompt_token_limit,
    prompt_tokens,
    select_items,
    summaries_equal,
)
from energie_sql_bench.scoring import summarize
from energie_sql_bench.semantic import SemanticLayer

REPO = Path(__file__).resolve().parents[2]
GOLD_SQL = "SELECT AVG(day_ahead_eur_mwh) AS a FROM dw.fact_preis"
Q1 = Question.model_validate(
    {
        "id": "q001",
        "split": "test",
        "tier": "T1",
        "de": "Preis?",
        "en": "Price?",
        "expect": "rows",
        "gold_sql": GOLD_SQL,
        "check_sql": "SELECT 1",
        "tables": ["dw.fact_preis"],
        "notes": "n",
    }
)
Q10 = Question.model_validate(
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
GOLD = {
    "q001": GoldEntry("q001", "rows", ResultSet(["a"], ["decimal"], [[Decimal("78.5")]]), "s", "d"),
    "q010": GoldEntry("q010", "abstain", None, None, "d"),
}
SCHEMA = {
    "database": "x",
    "tables": {
        "dw.fact_preis": {
            "type": "table",
            "columns": [{"name": "day_ahead_eur_mwh", "type": "decimal(9,2)", "nullable": True}],
            "primary_key": [],
            "foreign_keys": [],
            "values": None,
        }
    },
}
CTX = BenchContext(
    [Q1, Q10],
    GOLD,
    PromptContext(
        SCHEMA,
        {"tables": {}},
        SemanticLayer(source_commit="c", rules=[], synonyms={}, measures=[]),
        (),
        SnapshotSettings("2026-10-01", "2023-01-01", "2026-09-30", "2026-09", "2026-10-25", "c"),
    ),
)
V4 = VariantSpec("v4", "full", False, False)
PRICE = ModelPrice("anthropic", 1.0, 1.0, 1.0, 1.0, "x", "d")
CMP = CompareSettings(1e-4, 0.005)
OK = ExecResult(True, ResultSet(["x"], ["decimal"], [[Decimal("78.5")]]), None, None, 4.0)
BAD_COL = ExecResult(False, None, "42S22: Invalid column name 'x'.", "db_error", 1.0)


class ScriptedProvider:
    def __init__(self, answers: dict[tuple[str, int], object], usage: Usage = Usage(1000, 0, 0, 100)) -> None:  # noqa: B008
        self.answers = answers
        self.usage = usage
        self.requests: list[Request] = []

    def describe(self) -> dict:
        return {"provider": "scripted"}

    def complete(self, request: Request) -> Completion:
        self.requests.append(request)
        answer = self.answers[(request.item_id, request.attempt)]
        if isinstance(answer, Exception):
            raise answer
        return Completion(str(answer), self.usage, 7.0, {"stop_reason": "end_turn"})


class FakeExecutor:
    def __init__(self, results: dict[str, ExecResult]) -> None:
        self.results = results
        self.calls: list[str] = []

    def run(self, sql: str) -> ExecResult:
        self.calls.append(sql)
        return self.results[sql]

    def close(self) -> None:
        pass


def fence(sql: str) -> str:
    return f"```sql\n{sql}\n```"


def spec(**changes: object) -> RunSpec:
    base = {
        "run_id": "t",
        "provider": "scripted",
        "model": "m",
        "variant": "v4",
        "langs": ("de",),
        "max_usd": 100.0,
    }
    base.update(changes)
    return RunSpec(**base)


def test_single_shot_scores_and_labels() -> None:
    provider = ScriptedProvider(
        {("q001-de", 0): fence("SELECT x FROM dw.fact_preis"), ("q010-de", 0): "NICHT_BEANTWORTBAR"}
    )
    executor = FakeExecutor({"SELECT x FROM dw.fact_preis": BAD_COL})
    result = execute_run(spec(), V4, CTX, provider, executor, PRICE, CMP)
    q1, q10 = result.outcomes
    assert (q1.correct, q1.final_status, q1.labels) == (False, "db_error", ("E2",))
    assert (q10.correct, q10.final_status) == (True, "abstain")
    assert result.complete and len(result.responses) == 2
    assert result.cost_usd == pytest.approx(2 * 1100 / 1_000_000)


def test_responses_record_stop_reason_and_prompt_tokens() -> None:
    provider = ScriptedProvider({("q001-de", 0): fence(GOLD_SQL), ("q010-de", 0): "NICHT_BEANTWORTBAR"})
    result = execute_run(spec(), V4, CTX, provider, FakeExecutor({GOLD_SQL: OK}), PRICE, CMP)
    first = result.responses[0]
    assert first["meta"] == {"stop_reason": "end_turn"} and first["prompt_tokens"] == 1000
    assert first["prompt_hash"] and first["attempt"] == 0 and first["repeat"] == 0


def test_self_correction_repairs_db_error_and_block() -> None:
    provider = ScriptedProvider(
        {
            ("q001-de", 0): fence("DELETE FROM dw.fact_preis"),
            ("q001-de", 1): fence("SELECT x FROM dw.fact_preis"),
            ("q001-de", 2): fence(GOLD_SQL),
            ("q010-de", 0): "NICHT_BEANTWORTBAR",
        }
    )
    executor = FakeExecutor({"SELECT x FROM dw.fact_preis": BAD_COL, GOLD_SQL: OK})
    result = execute_run(spec(self_correct=True), V4, CTX, provider, executor, PRICE, CMP)
    q1 = result.outcomes[0]
    assert [a.status for a in q1.attempts] == ["blocked", "db_error", "ok"]
    assert q1.correct and q1.labels == ()
    assert "Invalid column name" in provider.requests[2].messages[-1][1]
    assert provider.requests[1].messages[-2][0] == "assistant"


def test_repairs_stop_after_two() -> None:
    provider = ScriptedProvider(
        {
            ("q001-de", 0): fence("SELECT x FROM dw.fact_preis"),
            ("q001-de", 1): fence("SELECT x FROM dw.fact_preis"),
            ("q001-de", 2): fence("SELECT x FROM dw.fact_preis"),
            ("q010-de", 0): "NICHT_BEANTWORTBAR",
        }
    )
    executor = FakeExecutor({"SELECT x FROM dw.fact_preis": BAD_COL})
    result = execute_run(spec(self_correct=True), V4, CTX, provider, executor, PRICE, CMP)
    assert len(result.outcomes[0].attempts) == 3 and not result.outcomes[0].correct
    assert executor.calls == ["SELECT x FROM dw.fact_preis"]  # identical SQL is executed once


def test_wrong_answer_is_not_repaired() -> None:
    wrong = ExecResult(True, ResultSet(["x"], ["decimal"], [[Decimal("1")]]), None, None, 1.0)
    provider = ScriptedProvider({("q001-de", 0): fence(GOLD_SQL), ("q010-de", 0): "NICHT_BEANTWORTBAR"})
    result = execute_run(
        spec(self_correct=True), V4, CTX, provider, FakeExecutor({GOLD_SQL: wrong}), PRICE, CMP
    )
    assert len(result.outcomes[0].attempts) == 1 and result.outcomes[0].labels == ("E?",)


def test_identical_sql_is_executed_once() -> None:
    provider = ScriptedProvider(
        {
            ("q001-de", 0): fence(GOLD_SQL),
            ("q001-en", 0): fence(GOLD_SQL),
            ("q010-de", 0): "NICHT_BEANTWORTBAR",
            ("q010-en", 0): "NICHT_BEANTWORTBAR",
        }
    )
    executor = FakeExecutor({GOLD_SQL: OK})
    result = execute_run(spec(langs=("de", "en")), V4, CTX, provider, executor, PRICE, CMP)
    assert executor.calls == [GOLD_SQL] and len(result.predictions) == 1
    assert sum(o.correct for o in result.outcomes) == 4


def test_cost_ceiling_stops_the_run() -> None:
    provider = ScriptedProvider({("q001-de", 0): fence(GOLD_SQL), ("q010-de", 0): "NICHT_BEANTWORTBAR"})
    result = execute_run(spec(max_usd=0.0005), V4, CTX, provider, FakeExecutor({GOLD_SQL: OK}), PRICE, CMP)
    assert not result.complete and "Kostenobergrenze" in result.aborted_reason
    assert len(result.outcomes) == 1


def test_three_provider_errors_abort() -> None:
    error = ProviderError("overloaded")
    provider = ScriptedProvider({("q001-de", 0): error, ("q010-de", 0): error})
    result = execute_run(spec(repeats=2), V4, CTX, provider, FakeExecutor({}), PRICE, CMP)
    assert not result.complete and "Providerfehler" in result.aborted_reason
    assert len(result.outcomes) == 3
    assert result.outcomes[0].labels == ("E0",) and result.responses[0]["error"] == "overloaded"


def test_a_success_resets_the_provider_error_counter() -> None:
    error = ProviderError("overloaded")
    provider = ScriptedProvider({("q001-de", 0): error, ("q010-de", 0): "NICHT_BEANTWORTBAR"})
    result = execute_run(spec(repeats=2), V4, CTX, provider, FakeExecutor({}), PRICE, CMP)
    assert result.complete and result.aborted_reason is None  # never three in a row: runs to the end
    assert [o.labels for o in result.outcomes] == [("E0",), (), ("E0",), ()]


def test_repeats_are_requested_and_recorded_per_repeat() -> None:
    provider = ScriptedProvider({("q001-de", 0): fence(GOLD_SQL), ("q010-de", 0): "NICHT_BEANTWORTBAR"})
    result = execute_run(spec(repeats=3), V4, CTX, provider, FakeExecutor({GOLD_SQL: OK}), PRICE, CMP)
    assert [r.repeat for r in provider.requests] == [0, 0, 1, 1, 2, 2]
    assert [o.repeat for o in result.outcomes] == [0, 0, 1, 1, 2, 2]
    assert result.complete and len(result.responses) == 6
    summary = summarize(result.outcomes, 3, 1.0)
    assert summary["n_items"] == 2 and summary["ex"]["interval"] == "bootstrap"


def test_prompt_above_the_token_limit_invalidates_the_run() -> None:
    provider = ScriptedProvider(
        {("q001-de", 0): fence(GOLD_SQL), ("q010-de", 0): "NICHT_BEANTWORTBAR"},
        usage=Usage(9000, 8000, 0, 10),
    )
    result = execute_run(
        spec(), V4, CTX, provider, FakeExecutor({GOLD_SQL: OK}), PRICE, CMP, token_limit=16000
    )
    assert not result.complete and "17000 Tokens über der Grenze 16000" in result.aborted_reason
    assert result.outcomes == [] and len(result.responses) == 1  # the offending response is still recorded
    assert result.responses[0]["prompt_tokens"] == 17000
    assert result.cost_usd == pytest.approx(17010 / 1_000_000)


def test_prompt_at_the_token_limit_is_accepted() -> None:
    provider = ScriptedProvider(
        {("q001-de", 0): fence(GOLD_SQL), ("q010-de", 0): "NICHT_BEANTWORTBAR"},
        usage=Usage(1000, 0, 15000, 10),
    )
    result = execute_run(
        spec(), V4, CTX, provider, FakeExecutor({GOLD_SQL: OK}), PRICE, CMP, token_limit=16000
    )
    assert result.complete and len(result.outcomes) == 2


def test_prompt_tokens_sum_all_input_kinds() -> None:
    assert prompt_tokens(Usage(1, 20, 300, 9999)) == 321


def test_prompt_token_limit_per_provider() -> None:
    settings = load_settings(REPO, environ={})
    assert prompt_token_limit(settings, "ollama") == 16384 - 1000
    assert prompt_token_limit(settings, "anthropic") == 16384
    assert prompt_token_limit(settings, "synthetic") is None


def test_estimate_cost_is_an_upper_bound_formula() -> None:
    items = select_items(CTX, spec())
    base = estimate_cost(spec(), V4, CTX, PRICE, items)
    assert base > 0
    assert estimate_cost(spec(self_correct=True), V4, CTX, PRICE, items) == pytest.approx(1.5 * base)
    assert estimate_cost(spec(repeats=3), V4, CTX, PRICE, items) == pytest.approx(3 * base)
    free = ModelPrice("synthetic", 0.0, 0.0, 0.0, 0.0, "x", "d")
    assert estimate_cost(spec(), V4, CTX, free, items) == 0.0


def test_select_items_respects_split_langs_and_limit() -> None:
    assert [i.item_id for i in select_items(CTX, spec(langs=("de", "en")))] == [
        "q001-de",
        "q001-en",
        "q010-de",
        "q010-en",
    ]
    assert [i.item_id for i in select_items(CTX, spec(limit=1))] == ["q001-de"]
    assert select_items(CTX, spec(split="dev")) == []


def test_run_spec_json_roundtrip() -> None:
    original = spec(langs=("de", "en"), repeats=3, self_correct=True, limit=5)
    assert RunSpec.from_json(original.to_json()) == original


def test_default_run_id() -> None:
    rid = default_run_id("ollama", "qwen2.5-coder:7b", "v4", True, "test", dt.date(2026, 10, 26))
    assert rid == "ollama-qwen2.5-coder-7b-v4-sc-test-20261026"
    assert default_run_id("anthropic", "claude-haiku-5-5", "v1", False, "dev", dt.date(2026, 1, 2)) == (
        "anthropic-claude-haiku-5-5-v1-dev-20260102"
    )


def test_recording_and_replay_reproduce_the_summary(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        {
            ("q001-de", 0): fence("SELECT x FROM dw.fact_preis"),
            ("q001-de", 1): fence(GOLD_SQL),
            ("q010-de", 0): "NICHT_BEANTWORTBAR",
        }
    )
    live = execute_run(
        spec(self_correct=True),
        V4,
        CTX,
        provider,
        FakeExecutor({"SELECT x FROM dw.fact_preis": BAD_COL, GOLD_SQL: OK}),
        PRICE,
        CMP,
    )
    live_summary = summarize(live.outcomes, 1, 1.1)
    write_run(tmp_path / "r", {"run_id": "r"}, live.responses, live.predictions, live_summary)
    files = read_run(tmp_path / "r")
    replayed = execute_run(
        spec(self_correct=True),
        V4,
        CTX,
        ReplayProvider(files.responses),
        RecordedExecutor(files.predictions),
        PRICE,
        CMP,
    )
    assert summaries_equal(summarize(replayed.outcomes, 1, 1.1), files.summary)
    assert not summaries_equal({"a": 1}, {"a": 2})


def test_replay_fails_loudly_when_the_prompt_changed() -> None:
    provider = ScriptedProvider({("q001-de", 0): fence(GOLD_SQL), ("q010-de", 0): "NICHT_BEANTWORTBAR"})
    live = execute_run(spec(), V4, CTX, provider, FakeExecutor({GOLD_SQL: OK}), PRICE, CMP)
    changed = VariantSpec("v4", "full", True, False)  # a different variant changes the system prompt
    ctx = BenchContext(
        CTX.questions,
        CTX.gold,
        PromptContext(
            CTX.prompt.schema,
            CTX.prompt.descriptions,
            SemanticLayer(source_commit="c", rules=["new rule"], synonyms={}, measures=[]),
            (),
            CTX.prompt.snapshot,
        ),
    )
    with pytest.raises(ReplayMiss):
        execute_run(
            spec(),
            changed,
            ctx,
            ReplayProvider(live.responses),
            RecordedExecutor(live.predictions),
            PRICE,
            CMP,
        )


def test_preflight_refuses_a_prompt_that_cannot_fit_the_local_context() -> None:
    from dataclasses import replace

    from energie_sql_bench.runner import RunError, _check_prompt_fits, load_context

    settings = load_settings(REPO, environ={})
    ctx = load_context(settings)
    run = spec(provider="ollama", model="qwen2.5-coder:7b", variant="v4", split="test", limit=2)
    items = select_items(ctx, run)
    _check_prompt_fits(settings, run, settings.variants["v4"], ctx, items)  # 16384 tokens: fits
    small = replace(settings, ollama=replace(settings.ollama, num_ctx=8192))
    with pytest.raises(RunError, match="geschätzter Prompt .* über der Grenze 7192"):
        _check_prompt_fits(small, run, small.variants["v4"], ctx, items)
    _check_prompt_fits(small, replace(run, provider="synthetic"), small.variants["v4"], ctx, items)
