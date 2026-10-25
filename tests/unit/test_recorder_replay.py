from decimal import Decimal
from pathlib import Path

import pytest

from energie_sql_bench.execute import ExecResult
from energie_sql_bench.gold import sql_sha256
from energie_sql_bench.llm.base import ProviderError, ReplayMiss, Request
from energie_sql_bench.llm.recorder import Journal, read_run, write_run
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


def test_line_separators_inside_a_response_survive_the_roundtrip(tmp_path: Path) -> None:
    # json.dumps(ensure_ascii=False) writes U+2028, U+2029 and U+0085 raw; str.splitlines() would cut there.
    text = "SELECT 1 -- a\u0085b c\x0cd\x1ce"
    rows = [{**RESPONSES[0], "text": text}, {**RESPONSES[0], "item_id": "q009-de", "text": " "}]
    write_run(tmp_path / "r", {}, rows, {}, {})
    assert " " in (tmp_path / "r" / "responses.jsonl").read_text(encoding="utf-8")
    assert read_run(tmp_path / "r").responses == rows


def test_journal_appends_and_survives_line_separators(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "partial")
    assert not journal.exists()
    journal.start({"run_id": "r"})
    rows = [{**RESPONSES[0], "text": "a b"}, {**RESPONSES[0], "item_id": "q002-de", "text": "\u0085"}]
    for row in rows:
        journal.append(row)
    config, loaded = Journal(tmp_path / "partial").load()
    assert config == {"run_id": "r"} and loaded == rows
    journal.discard()
    assert not (tmp_path / "partial").exists()


def test_journal_drops_only_a_torn_last_line(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "partial")
    journal.start({})
    journal.append(RESPONSES[0])
    with journal.responses_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write('{"item_id": "q00')  # killed mid-write
    _, loaded = journal.load()
    assert loaded == [RESPONSES[0]]
    journal.append(RESPONSES[1])  # the file was repaired, so appending is safe
    assert journal.load()[1] == RESPONSES
    journal.responses_path.write_text('not json\n{"a": 1}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        journal.load()  # a bad line that is not the tail is corruption, never skipped


def test_a_committed_run_with_a_torn_line_is_an_error(tmp_path: Path) -> None:
    write_run(tmp_path / "r", {}, RESPONSES, {}, {})
    path = tmp_path / "r" / "responses.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + '{"item', encoding="utf-8", newline="\n")
    with pytest.raises(ValueError):
        read_run(tmp_path / "r")
