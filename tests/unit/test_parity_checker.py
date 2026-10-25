"""run_parity must be able to fail. An in-memory DuckDB and hand-built gold entries drive every status
(match, mismatch, error, skip, missing); a checker that always said "match" would break these tests."""

from decimal import Decimal

import duckdb
import pytest

from energie_sql_bench.config import CompareSettings
from energie_sql_bench.gold import GoldEntry, sql_sha256
from energie_sql_bench.questions import Question
from energie_sql_bench.resultset import ResultSet
from energie_sql_bench.sample import ParityRow, is_nontrivial, parity_summary, run_parity

COMPARE = CompareSettings(rel_tol=1e-4, abs_tol=0.005)
SQL = "SELECT a, b FROM dw.t ORDER BY a"


@pytest.fixture
def con():
    connection = duckdb.connect()
    connection.execute("CREATE SCHEMA dw")
    connection.execute("CREATE TABLE dw.t (a INTEGER, b DECIMAL(10, 2))")
    connection.execute("INSERT INTO dw.t VALUES (1, 10.50), (2, 20.00), (3, 1000.00)")
    yield connection
    connection.close()


def question(qid: str = "q001", sql: str = SQL, **changes: object) -> Question:
    data = {
        "id": qid,
        "split": "test",
        "tier": "T1",
        "de": f"Frage {qid} auf Deutsch",
        "en": f"Question {qid} in English",
        "expect": "rows",
        "gold_sql": sql,
        "check_sql": sql,
        "notes": "Test",
    }
    data.update(changes)
    return Question(**data)


def result(rows: list[list[object]], columns: tuple[str, ...] = ("a", "b")) -> ResultSet:
    types = ["int", "decimal"][: len(columns)]
    return ResultSet(list(columns), types, rows)


def gold(
    q: Question, rows: list[list[object]], columns: tuple[str, ...] = ("a", "b")
) -> dict[str, GoldEntry]:
    return {q.id: GoldEntry(q.id, "rows", result(rows, columns), sql_sha256(q.gold_sql or ""), "sample")}


GOOD = [[1, Decimal("10.50")], [2, Decimal("20.00")], [3, Decimal("1000.00")]]


def status_of(con, q: Question, entries: dict[str, GoldEntry]) -> ParityRow:
    (row,) = run_parity(con, [q], entries, COMPARE)
    return row


def test_identical_result_matches(con) -> None:
    q = question()
    row = status_of(con, q, gold(q, GOOD))
    assert (row.status, row.nontrivial) == ("match", True)


def test_one_perturbed_cell_is_a_mismatch(con) -> None:
    q = question()
    wrong = [[1, Decimal("10.50")], [2, Decimal("25.00")], [3, Decimal("1000.00")]]
    assert status_of(con, q, gold(q, wrong)).status == "mismatch"


def test_a_missing_row_is_a_mismatch(con) -> None:
    q = question()
    assert status_of(con, q, gold(q, GOOD[:2])).status == "mismatch"


def test_the_tolerance_is_applied_in_both_directions(con) -> None:
    q = question()
    inside = [[1, Decimal("10.50")], [2, Decimal("20.00")], [3, Decimal("1000.04")]]  # 4e-5 relative
    outside = [[1, Decimal("10.50")], [2, Decimal("20.00")], [3, Decimal("1000.20")]]  # 2e-4 relative
    assert status_of(con, q, gold(q, inside)).status == "match"
    assert status_of(con, q, gold(q, outside)).status == "mismatch"


def test_a_question_tolerance_overrides_the_default(con) -> None:
    q = question(tolerance={"rel": 0.01, "abs": 0.0})
    off_by_one_percent = [[1, Decimal("10.50")], [2, Decimal("20.00")], [3, Decimal("1005.00")]]
    assert status_of(con, q, gold(q, off_by_one_percent)).status == "match"


def test_an_extra_column_fails_the_strict_comparison(con) -> None:
    q = question()
    narrower = [[1], [2], [3]]
    row = status_of(con, q, gold(q, narrower, columns=("a",)))
    assert row.status == "mismatch"  # EX would accept the extra column, parity requires the same shape


def test_failing_sql_is_an_error(con) -> None:
    q = question(sql="SELECT a FROM dw.missing_table")
    row = status_of(con, q, gold(q, [[1]], columns=("a",)))
    assert row.status == "error" and row.reason


def test_a_changed_gold_sql_makes_the_stored_gold_missing(con) -> None:
    q = question()
    stale = {q.id: GoldEntry(q.id, "rows", result(GOOD), sql_sha256("SELECT 1 AS a, 2 AS b"), "sample")}
    assert status_of(con, q, stale).status == "missing"
    assert status_of(con, q, {}).status == "missing"


def test_skip_and_abstain(con) -> None:
    skipped = question("q002", duckdb="skip: FORMAT hat kein Gegenstück")
    abstain = question("q003", expect="abstain", tier="A", gold_sql=None, check_sql=None)
    rows = run_parity(con, [skipped, abstain], {}, COMPARE)
    assert [(r.id, r.status) for r in rows] == [("q002", "skip")]
    assert rows[0].reason == "FORMAT hat kein Gegenstück"


def test_summary_counts_every_status(con) -> None:
    ok, bad, broken, skipped, stale = (
        question("q001"),
        question("q002"),
        question("q003", sql="SELECT a FROM dw.missing_table"),
        question("q004", duckdb="skip: nicht übersetzbar hier"),
        question("q005"),
    )
    entries = {
        **gold(ok, GOOD),
        **gold(bad, [[1, Decimal("99.00")]]),
        **gold(broken, [[1]], columns=("a",)),
    }
    rows = run_parity(con, [ok, bad, broken, skipped, stale], entries, COMPARE)
    summary = parity_summary(rows)
    assert [r.status for r in rows] == ["match", "mismatch", "error", "skip", "missing"]
    assert (summary["intents"], summary["matched"], summary["mismatched"]) == (5, 1, 1)
    assert (summary["errors"], summary["skipped"], summary["missing"]) == (1, 1, 1)
    assert summary["coverage"] == 0.2


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([], False),
        ([[None]], False),
        ([[None, None], [None, None]], False),
        ([[0]], False),
        ([[Decimal("0.000")]], False),
        ([[0, None], [0.0, Decimal("0")]], False),
        ([[1]], True),
        ([[0, None], [0, Decimal("0.001")]], True),
        ([["x"]], True),
        ([[None, "Bayern"]], True),
        ([[False]], True),  # a bit column is a value, not a zero count
    ],
)
def test_non_trivial_excludes_empty_null_and_zero_results(rows, expected) -> None:
    assert is_nontrivial(ResultSet(["x"] * (len(rows[0]) if rows else 1), ["int"], rows)) is expected


def test_a_trivial_match_is_not_counted_as_non_trivial(con) -> None:
    q = question("q001", sql="SELECT COUNT(*) AS n FROM dw.t WHERE a > 100")
    entries = {
        q.id: GoldEntry(q.id, "rows", ResultSet(["n"], ["int"], [[0]]), sql_sha256(q.gold_sql or ""), "x")
    }
    row = status_of(con, q, entries)
    assert (row.status, row.nontrivial) == ("match", False)
