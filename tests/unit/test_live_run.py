"""live_run and _check_snapshot with a fake provider and a fake database: wiring of the budget chain, snapshot
refusal, order of the checks, and a journaled run that survives an interruption and resumes."""

import json
import shutil
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from energie_sql_bench import runner
from energie_sql_bench.config import Settings, load_settings
from energie_sql_bench.execute import ExecResult
from energie_sql_bench.files import read_json
from energie_sql_bench.llm.base import Completion, ProviderError, Request
from energie_sql_bench.llm.recorder import read_lines
from energie_sql_bench.llm.synthetic import SyntheticProvider
from energie_sql_bench.records import Usage
from energie_sql_bench.resultset import ResultSet
from energie_sql_bench.runner import RunError, RunSpec, live_run, replay_run

REPO = Path(__file__).resolve().parents[2]
OLLAMA_LIMIT = 16384 - 1000
OK = ExecResult(True, ResultSet(["x"], ["decimal"], [[Decimal("1")]]), None, None, 1.0)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    for name in ("bench", "schema", "semantic", "snapshot"):
        shutil.copytree(REPO / name, tmp_path / name)
    for name in ("config.toml", "pricing.toml", "pyproject.toml"):
        shutil.copy(REPO / name, tmp_path / name)
    return load_settings(tmp_path, environ={})


class FakeExecutor:
    def __init__(self, *_: object) -> None:
        pass

    def run(self, sql: str) -> ExecResult:
        return OK

    def close(self) -> None:
        pass


class ScriptedLive:
    """The synthetic answers, a fixed usage, and a chosen failure on the n-th call (1-based)."""

    def __init__(
        self,
        questions: list,
        usage: Usage = Usage(1000, 0, 0, 50),  # noqa: B008
        fail: dict[int, BaseException] | None = None,
        unknown_tokens: bool = False,
        meta: dict | None = None,
    ) -> None:
        self.inner = SyntheticProvider(questions)
        self.usage = usage
        self.fail = fail or {}
        self.requests: list[Request] = []
        self.unknown_tokens = unknown_tokens
        self.meta = meta or {"provider": "scripted"}

    def describe(self) -> dict:
        return dict(self.meta)

    def complete(self, request: Request) -> Completion:
        self.requests.append(request)
        if len(self.requests) in self.fail:
            raise self.fail[len(self.requests)]
        text = self.inner.complete(request).text
        return Completion(text, self.usage, 3.0, {"stop_reason": "end_turn"}, not self.unknown_tokens)


@pytest.fixture
def wiring(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """Replace the snapshot check, the provider factory and the database; returns the created providers."""
    created: list[ScriptedLive] = []
    plan: dict = {"kwargs": {}}

    def make(name: str, model: str, settings: Settings, questions: list) -> ScriptedLive:
        provider = ScriptedLive(questions, **plan["kwargs"])
        created.append(provider)
        return provider

    monkeypatch.setattr(runner, "_check_snapshot", lambda settings: "digest-1")
    monkeypatch.setattr("energie_sql_bench.llm.make_provider", make)
    monkeypatch.setattr("energie_sql_bench.execute.MssqlExecutor", FakeExecutor)
    return created, plan


def spec(**changes: object) -> RunSpec:
    base = {
        "run_id": "live-1",
        "provider": "ollama",
        "model": "qwen2.5-coder:7b",
        "variant": "v4",
        "langs": ("de",),
        "limit": 4,
        "max_usd": 5.0,
    }
    base.update(changes)
    return RunSpec(**base)


def rows_of(path: Path) -> list[dict]:
    return read_lines(path)


def journal_rows(settings: Settings, run_id: str = "live-1") -> list[dict]:
    return rows_of(settings.path(f"results/partial/{run_id}/responses.jsonl"))


@pytest.mark.parametrize(
    "failure", [KeyboardInterrupt(), RuntimeError("adapter bug"), ValueError("bad body")]
)
def test_interrupted_run_keeps_its_responses_and_resumes(settings: Settings, wiring, failure) -> None:  # noqa: ANN001
    created, plan = wiring
    plan["kwargs"] = {"fail": {3: failure}}
    with pytest.raises(type(failure)):
        live_run(settings, spec())
    assert len(journal_rows(settings)) == 2  # the two paid responses are on disk
    assert not settings.path("results/runs/live-1").exists()

    plan["kwargs"] = {}
    run_dir, summary = live_run(settings, spec())
    resumed = created[-1]
    assert [r.item_id for r in resumed.requests] == [
        "q003-de",
        "q004-de",
    ]  # recorded items are not asked again
    assert summary["complete"] and summary["n_items"] == 4
    assert not settings.path("results/partial/live-1").exists()

    # the resumed run is indistinguishable from one that was never interrupted
    plan["kwargs"] = {}
    clean_dir, clean_summary = live_run(settings, spec(run_id="live-clean"))
    assert (run_dir / "responses.jsonl").read_bytes() == (clean_dir / "responses.jsonl").read_bytes()
    assert summary == clean_summary


def test_provider_errors_are_retried_on_resume(settings: Settings, wiring) -> None:  # noqa: ANN001
    created, plan = wiring
    plan["kwargs"] = {"fail": {2: ProviderError("overloaded"), 3: KeyboardInterrupt()}}
    with pytest.raises(KeyboardInterrupt):
        live_run(settings, spec())
    rows = journal_rows(settings)
    assert [bool(r["error"]) for r in rows] == [False, True]

    plan["kwargs"] = {}
    run_dir, summary = live_run(settings, spec())
    assert [r.item_id for r in created[-1].requests] == ["q002-de", "q003-de", "q004-de"]
    final = rows_of(run_dir / "responses.jsonl")
    assert len(final) == 4 and not any(r["error"] for r in final)
    assert summary["complete"]


def test_a_partial_run_from_other_settings_is_refused(settings: Settings, wiring) -> None:  # noqa: ANN001
    _, plan = wiring
    plan["kwargs"] = {"fail": {2: KeyboardInterrupt()}}
    with pytest.raises(KeyboardInterrupt):
        live_run(settings, spec())
    plan["kwargs"] = {}
    with pytest.raises(RunError, match="Teillauf live-1 stammt aus anderen Einstellungen"):
        live_run(settings, spec(limit=6))
    assert len(journal_rows(settings)) == 1  # the refusal touched nothing


def test_a_finished_run_is_never_resumed_or_overwritten(settings: Settings, wiring) -> None:  # noqa: ANN001
    live_run(settings, spec())
    with pytest.raises(RunError, match="existiert bereits"):
        live_run(settings, spec())


def test_live_run_refuses_a_prompt_that_cannot_fit_the_local_context(settings: Settings, wiring) -> None:  # noqa: ANN001
    created, _ = wiring
    small = replace(settings, ollama=replace(settings.ollama, num_ctx=8192))
    with pytest.raises(RunError, match="geschätzter Prompt .* über der Grenze 7192"):
        live_run(small, spec())
    assert created == []  # refused before any provider exists
    assert not small.path("results/partial/live-1").exists()


def test_live_run_stores_and_enforces_the_token_limit(settings: Settings, wiring) -> None:  # noqa: ANN001
    _, plan = wiring
    plan["kwargs"] = {"usage": Usage(OLLAMA_LIMIT + 1, 0, 0, 10)}
    run_dir, summary = live_run(settings, spec())
    assert read_json(run_dir / "config.json")["prompt_token_limit"] == OLLAMA_LIMIT
    assert not summary["complete"] and f"über der Grenze {OLLAMA_LIMIT}" in summary["aborted_reason"]
    assert summary["n_items"] == 0

    recomputed, stored = replay_run(settings, "live-1")  # the stored limit is applied again on replay
    assert not recomputed["complete"] and recomputed == stored


def test_a_prompt_exactly_at_the_limit_completes(settings: Settings, wiring) -> None:  # noqa: ANN001
    _, plan = wiring
    plan["kwargs"] = {"usage": Usage(OLLAMA_LIMIT, 0, 0, 10)}
    _, summary = live_run(settings, spec())
    assert summary["complete"] and summary["n_items"] == 4


def test_an_unknown_prompt_size_fails_the_budget_closed(settings: Settings, wiring) -> None:  # noqa: ANN001
    _, plan = wiring
    plan["kwargs"] = {"usage": Usage(0, 0, 0, 10), "unknown_tokens": True}
    run_dir, summary = live_run(settings, spec())
    assert not summary["complete"] and "unbekannt" in summary["aborted_reason"]
    assert summary["n_items"] == 0
    rows = rows_of(run_dir / "responses.jsonl")
    assert len(rows) == 1 and rows[0]["prompt_tokens"] is None
    recomputed, stored = replay_run(settings, "live-1")
    assert recomputed == stored and not recomputed["complete"]


def test_snapshot_drift_stops_before_the_database(
    settings: Settings, wiring, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    created, _ = wiring

    def drift(settings: Settings) -> str:
        raise RunError("Snapshot weicht ab (1 Abweichungen): esb snapshot --check")

    def no_database(*_: object) -> None:
        raise AssertionError("database opened despite snapshot drift")

    monkeypatch.setattr(runner, "_check_snapshot", drift)
    monkeypatch.setattr("energie_sql_bench.execute.MssqlExecutor", no_database)
    with pytest.raises(RunError, match="Snapshot weicht ab"):
        live_run(settings, spec())
    assert not settings.path("results/partial/live-1").exists()
    assert not settings.path("results/runs/live-1").exists()


def test_missing_api_key_stops_before_the_snapshot_check(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def must_not_run(settings: Settings) -> str:
        raise AssertionError("snapshot check ran before the provider was created")

    monkeypatch.setattr(runner, "_check_snapshot", must_not_run)
    with pytest.raises((RunError, ProviderError), match="ANTHROPIC_API_KEY fehlt"):
        live_run(settings, spec(provider="anthropic", model="claude-haiku-5-5", max_usd=50.0))


class FakeConnection:
    closed = False

    def close(self) -> None:
        self.closed = True


def patch_snapshot_db(monkeypatch: pytest.MonkeyPatch, live: dict) -> FakeConnection:
    con = FakeConnection()
    monkeypatch.setattr("energie_sql_bench.execute.connect_mssql", lambda db, *a: con)
    monkeypatch.setattr("energie_sql_bench.snapshot.compute_fingerprint", lambda fetch, snapshot: live)
    return con


def test_check_snapshot_returns_the_stored_digest(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = read_json(settings.path("snapshot/fingerprint.json"))
    con = patch_snapshot_db(monkeypatch, json.loads(json.dumps(stored)))
    assert runner._check_snapshot(settings) == stored["digest"]
    assert con.closed


def test_check_snapshot_refuses_drift_and_closes_the_connection(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = read_json(settings.path("snapshot/fingerprint.json"))
    live = json.loads(json.dumps(stored))
    live["cut"]["smard_end"] = "2026-10-31"
    con = patch_snapshot_db(monkeypatch, live)
    with pytest.raises(RunError, match=r"Snapshot weicht ab \(\d+ Abweichungen\)"):
        runner._check_snapshot(settings)
    assert con.closed


OLLAMA_META = {
    "digest": "sha-a",
    "model": "qwen2.5-coder:7b",
    "num_ctx": 16384,
    "num_predict": 1000,
    "provider": "ollama",
    "seed": 42,
    "temperature": 0,
}
ANTHROPIC_META = {
    "cache": True,
    "effort": "low",
    "max_tokens": 2000,
    "model": "claude-haiku-5-5",
    "provider": "anthropic",
    "sdk": "1.17.0",
}


@pytest.mark.parametrize(
    ("meta", "key", "other"),
    [
        (OLLAMA_META, "digest", "sha-b"),
        (OLLAMA_META, "seed", 43),
        (OLLAMA_META, "num_predict", 500),
        (OLLAMA_META, "num_ctx", 8192),
        (OLLAMA_META, "temperature", 0.7),
        (ANTHROPIC_META, "model", "claude-sonnet-5-5"),
        (ANTHROPIC_META, "effort", "high"),
        (ANTHROPIC_META, "max_tokens", 4000),
        (ANTHROPIC_META, "cache", False),
    ],
)
def test_a_resume_refuses_changed_provider_settings(
    settings: Settings,
    wiring,  # noqa: ANN001
    meta: dict,
    key: str,
    other: object,
) -> None:
    _, plan = wiring
    plan["kwargs"] = {"meta": meta, "fail": {2: KeyboardInterrupt()}}
    with pytest.raises(KeyboardInterrupt):
        live_run(settings, spec())
    plan["kwargs"] = {"meta": {**meta, key: other}}
    with pytest.raises(RunError, match="Teillauf live-1 stammt aus anderen Einstellungen"):
        live_run(settings, spec())
    assert len(journal_rows(settings)) == 1  # nothing was mixed in or discarded


def test_a_resume_ignores_the_sdk_version_only(settings: Settings, wiring) -> None:  # noqa: ANN001
    created, plan = wiring
    plan["kwargs"] = {"meta": ANTHROPIC_META, "fail": {3: KeyboardInterrupt()}}
    with pytest.raises(KeyboardInterrupt):
        live_run(settings, spec())
    plan["kwargs"] = {"meta": {**ANTHROPIC_META, "sdk": "1.18.2"}}
    _, summary = live_run(settings, spec())
    assert summary["complete"] and [r.item_id for r in created[-1].requests] == ["q003-de", "q004-de"]
    assert not settings.path("results/partial/live-1").exists()
