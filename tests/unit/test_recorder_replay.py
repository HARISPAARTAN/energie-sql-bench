from decimal import Decimal
from pathlib import Path

import pytest

from energie_sql_bench.execute import ExecResult
from energie_sql_bench.gold import sql_sha256
from energie_sql_bench.llm.base import ProviderError, ReplayMiss, Request
from energie_sql_bench.llm.recorder import read_run, write_run
from energie_sql_bench.llm.replay import RecordedExecutor, ReplayProvider
from energie_sql_bench.resultset import ResultSet

RESPONSES = [
    {
        "attempt": 0,
        "error": None,
        "item_id": "q001-de",
        "llm_ms": 12.5,
        "meta": {},
        "model": "m",
        "prompt_hash": "h1",
        "repeat": 0,
        "text": "```sql\nSELECT 1\n```",
        "usage": {"input_tokens": 5, "output_tokens": 2},
    },
    {
        "attempt": 0,
        "error": "overloaded",
        "item_id": "q002-de",
        "llm_ms": 0.0,
        "meta": {},
        "model": "m",
        "prompt_hash": "h2",
        "repeat": 0,
        "text": None,
        "usage": {},
    },
]
EXEC = ExecResult(True, ResultSet(["a"], ["decimal"], [[Decimal("1.5")]]), None, None, 3.25)


def test_roundtrip(tmp_path: Path) -> None:
    write_run(tmp_path / "r", {"run_id": "r"}, RESPONSES, {sql_sha256("SELECT 1"): EXEC.to_json()}, {"ex": 1})
    files = read_run(tmp_path / "r")
    assert files.config == {"run_id": "r"} and files.summary == {"ex": 1}
    assert files.responses == RESPONSES
    assert ExecResult.from_json(files.predictions[sql_sha256("SELECT 1")]) == EXEC


def test_gzip_is_deterministic(tmp_path: Path) -> None:
    preds = {sql_sha256("SELECT 1"): EXEC.to_json()}
    write_run(tmp_path / "a", {}, [], preds, {})
    write_run(tmp_path / "b", {}, [], preds, {})
    assert (tmp_path / "a" / "predictions.jsonl.gz").read_bytes() == (
        tmp_path / "b" / "predictions.jsonl.gz"
    ).read_bytes()


def test_missing_run_is_reported(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Lauf nicht gefunden"):
        read_run(tmp_path / "nope")


def test_replay_provider() -> None:
    provider = ReplayProvider(RESPONSES)
    ok = provider.complete(Request("q001-de", "m", "S", (), "h1", 0, 0))
    assert ok.text.startswith("```sql") and ok.usage.input_tokens == 5 and ok.llm_ms == 12.5
    with pytest.raises(ProviderError, match="overloaded"):
        provider.complete(Request("q002-de", "m", "S", (), "h2", 0, 0))
    with pytest.raises(ReplayMiss):
        provider.complete(Request("q003-de", "m", "S", (), "h3", 0, 0))


def test_replay_provider_keys_on_model_repeat_and_attempt() -> None:
    provider = ReplayProvider(RESPONSES)
    for request in (
        Request("q001-de", "other", "S", (), "h1", 0, 0),
        Request("q001-de", "m", "S", (), "h1", 1, 0),
        Request("q001-de", "m", "S", (), "h1", 0, 1),
    ):
        with pytest.raises(ReplayMiss):
            provider.complete(request)


def test_recorded_executor() -> None:
    executor = RecordedExecutor({sql_sha256("SELECT 1"): EXEC.to_json()})
    assert executor.run("  SELECT 1 \n") == EXEC
    with pytest.raises(ReplayMiss):
        executor.run("SELECT 2")
