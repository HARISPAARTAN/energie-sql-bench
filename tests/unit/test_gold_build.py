from decimal import Decimal
from pathlib import Path

from energie_sql_bench.config import CompareSettings
from energie_sql_bench.execute import ExecResult
from energie_sql_bench.gold import (
    GoldEntry,
    build_gold,
    canonical_rows,
    load_gold,
    sql_sha256,
    stale_gold,
    write_gold,
)
from energie_sql_bench.questions import Question
from energie_sql_bench.resultset import ResultSet

GOLD = "SELECT AVG(day_ahead_eur_mwh) AS a FROM dw.fact_preis"
CHECK = "SELECT AVG(day_ahead_eur_mwh) AS b FROM rpt.v_preis"
CMP = CompareSettings(1e-4, 0.005)


def q(**changes) -> Question:
    data = {
        "id": "q001",
        "split": "test",
        "tier": "T1",
        "de": "Preis?",
        "en": "Price?",
        "expect": "rows",
        "gold_sql": GOLD,
        "check_sql": CHECK,
        "tables": ["dw.fact_preis"],
        "notes": "n",
    }
    data.update(changes)
    return Question.model_validate(data)


def ok(value: str) -> ExecResult:
    return ExecResult(True, ResultSet(["a"], ["decimal"], [[Decimal(value)]]), None, None, 1.0)


class FakeExecutor:
    def __init__(self, answers: dict[str, list[ExecResult]]) -> None:
        self.answers = answers

    def run(self, sql: str) -> ExecResult:
        return self.answers[sql].pop(0)

    def close(self) -> None:
        pass


def test_good_question_and_abstain() -> None:
    ex = FakeExecutor({GOLD: [ok("78.51"), ok("78.51")], CHECK: [ok("78.512")]})
    abstain = q(id="q010", tier="A", expect="abstain", gold_sql=None, check_sql=None, tables=[])
    entries, errors = build_gold([q(), abstain], ex, "d1", 1000, CMP)
    assert errors == []
    assert entries["q001"].result.rows == [[Decimal("78.51")]]
    assert entries["q001"].sql_sha256 == sql_sha256(GOLD)
    assert entries["q010"].expect == "abstain" and entries["q010"].result is None


def test_failures_are_reported_and_not_written() -> None:
    ex = FakeExecutor({GOLD: [ok("1"), ok("2")], CHECK: [ok("1")]})
    entries, errors = build_gold([q()], ex, "d1", 1000, CMP)
    assert "q001" not in entries
    assert any("nicht reproduzierbar" in e for e in errors)


def test_check_mismatch_and_tables() -> None:
    ex = FakeExecutor({GOLD: [ok("1"), ok("1")], CHECK: [ok("5")]})
    entries, errors = build_gold([q(tables=["dw.fact_last"])], ex, "d1", 1000, CMP)
    assert any("Gegenprobe" in e for e in errors)
    assert any("tables muss ['dw.fact_preis'] sein" in e for e in errors)


def test_roundtrip_files(tmp_path: Path) -> None:
    entry = GoldEntry("q001", "rows", ResultSet(["a"], ["decimal"], [[Decimal("1.50")]]), "abc", "d1")
    write_gold({"q001": entry}, tmp_path)
    assert load_gold(tmp_path)["q001"] == entry


def multi(*values: str) -> ExecResult:
    return ExecResult(True, ResultSet(["a"], ["decimal"], [[Decimal(v)] for v in values]), None, None, 1.0)


def test_unordered_rows_are_stored_in_canonical_order_and_reproducible_in_any_order() -> None:
    ex = FakeExecutor({GOLD: [multi("3", "1", "2"), multi("2", "3", "1")], CHECK: [multi("1", "2", "3")]})
    entries, errors = build_gold([q()], ex, "d1", 1000, CMP)
    assert errors == []
    assert entries["q001"].result.rows == [[Decimal("1")], [Decimal("2")], [Decimal("3")]]


def test_ordered_rows_keep_the_query_order_and_order_changes_are_not_reproducible() -> None:
    ex = FakeExecutor({GOLD: [multi("3", "1"), multi("1", "3")], CHECK: [multi("3", "1")]})
    entries, errors = build_gold([q(ordered=True)], ex, "d1", 1000, CMP)
    assert any("nicht reproduzierbar" in e for e in errors) and "q001" not in entries
    ex = FakeExecutor({GOLD: [multi("3", "1"), multi("3", "1")], CHECK: [multi("3", "1")]})
    entries, errors = build_gold([q(ordered=True)], ex, "d1", 1000, CMP)
    assert errors == [] and entries["q001"].result.rows == [[Decimal("3")], [Decimal("1")]]


def test_canonical_rows_handles_mixed_null_and_text() -> None:
    result = ResultSet(["a", "b"], ["str", "int"], [["b", None], ["a", 2], ["a", None]])
    assert canonical_rows(result).rows == [["a", 2], ["a", None], ["b", None]]


def test_guard_blocked_query_is_not_executed() -> None:
    ex = FakeExecutor({})  # any run() would raise KeyError
    entries, errors = build_gold([q(gold_sql="DELETE FROM dw.fact_preis")], ex, "d1", 1000, CMP)
    assert "q001" not in entries and any("vom Guard blockiert" in e for e in errors)


def test_other_failure_branches() -> None:
    boom = ExecResult(False, None, "kaputt", "db_error", 0.1)
    ex = FakeExecutor({GOLD: [boom]})
    assert any("gold_sql fehlgeschlagen" in e for e in build_gold([q()], ex, "d1", 1000, CMP)[1])
    ex = FakeExecutor({GOLD: [ok("1"), ok("1")], CHECK: [boom]})
    assert any("check_sql fehlgeschlagen" in e for e in build_gold([q()], ex, "d1", 1000, CMP)[1])
    empty = ExecResult(True, ResultSet(["a"], ["decimal"], []), None, None, 1.0)
    ex = FakeExecutor({GOLD: [empty, empty], CHECK: [empty]})
    assert any("leeres Gold-Ergebnis" in e for e in build_gold([q()], ex, "d1", 1000, CMP)[1])
    ex = FakeExecutor({GOLD: [multi("1", "2", "3"), multi("1", "2", "3")], CHECK: [multi("1", "2", "3")]})
    assert any("mehr als 2 Zeilen" in e for e in build_gold([q()], ex, "d1", 2, CMP)[1])


def test_stale_gold_lists_files_frozen_against_another_digest() -> None:
    a = GoldEntry("q001", "rows", None, "x", "old")
    b = GoldEntry("q002", "rows", None, "x", "new")
    assert stale_gold({"q001": a, "q002": b}, "new") == ["q001"]
    assert stale_gold({"q002": b}, "new") == []
