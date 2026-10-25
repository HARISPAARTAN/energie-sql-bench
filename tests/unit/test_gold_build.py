from decimal import Decimal
from pathlib import Path

from energie_sql_bench.config import CompareSettings
from energie_sql_bench.execute import ExecResult
from energie_sql_bench.gold import GoldEntry, build_gold, load_gold, sql_sha256, write_gold
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
