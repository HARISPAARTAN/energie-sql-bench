from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from energie_sql_bench.config import load_settings
from energie_sql_bench.files import dump_json, read_json
from energie_sql_bench.gold import load_gold, sql_sha256
from energie_sql_bench.questions import load_questions
from energie_sql_bench.resultset import ResultSet
from energie_sql_bench.sample import load_duckdb, parity_summary, run_parity

REPO = Path(__file__).resolve().parents[2]
SETTINGS = load_settings(REPO, environ={})
QUESTIONS = load_questions(REPO / "bench" / "questions")


def test_sample_gold_is_current() -> None:
    gold = load_gold(REPO / "data" / "sample" / "gold_mssql")
    for q in QUESTIONS:
        if q.expect == "rows":
            assert q.id in gold, q.id
            assert gold[q.id].sql_sha256 == sql_sha256(q.gold_sql or ""), f"{q.id}: esb sample gold"


def test_parity_reproduces_and_meets_the_bar() -> None:
    con = load_duckdb(REPO / "data" / "sample")
    try:
        rows = run_parity(
            con, QUESTIONS, load_gold(REPO / "data" / "sample" / "gold_mssql"), SETTINGS.compare
        )
    finally:
        con.close()
    summary = parity_summary(rows)
    assert dump_json(summary) == dump_json(read_json(REPO / "data" / "sample" / "parity.json"))
    assert summary["intents"] == sum(q.expect == "rows" for q in QUESTIONS) == 64
    assert summary["mismatched"] == 0 and summary["errors"] == 0 and summary["missing"] == 0
    assert summary["coverage"] >= 0.8
    assert summary["matched_nontrivial"] >= 15


def test_every_skip_has_a_reason() -> None:
    for q in QUESTIONS:
        if not q.duckdb_ok:
            assert len(q.duckdb.removeprefix("skip: ").strip()) >= 10, q.id


def _parity_with(gold: dict) -> dict:
    con = load_duckdb(REPO / "data" / "sample")
    try:
        return {r.id: r for r in run_parity(con, QUESTIONS, gold, SETTINGS.compare)}
    finally:
        con.close()


def _shift_first_value(gold: dict, qid: str, factor: Decimal) -> dict:
    entry = gold[qid]
    rows = [list(r) for r in entry.result.rows]
    rows[0][1] = rows[0][1] * factor
    perturbed = ResultSet(entry.result.columns, entry.result.types, rows, entry.result.truncated)
    return {**gold, qid: replace(entry, result=perturbed)}


def test_the_checker_fails_on_a_perturbed_real_gold_cell() -> None:
    gold = load_gold(REPO / "data" / "sample" / "gold_mssql")
    assert _parity_with(gold)["q003"].status == "match"  # the unperturbed baseline
    rows = _parity_with(_shift_first_value(gold, "q003", Decimal("1.03")))  # +3 % in the largest state
    assert [qid for qid, r in rows.items() if r.status == "mismatch"] == ["q003"]
    # a shift inside the tolerance (rel 1e-4) still matches
    assert _parity_with(_shift_first_value(gold, "q003", Decimal("1.00003")))["q003"].status == "match"
