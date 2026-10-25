from collections import Counter
from pathlib import Path

import pytest

from energie_sql_bench.files import read_json
from energie_sql_bench.questions import Question, build_items, load_questions
from energie_sql_bench.schema import unknown_columns

REPO = Path(__file__).resolve().parents[2]
QUESTIONS = load_questions(REPO / "bench" / "questions")
SCHEMA = read_json(REPO / "schema" / "schema.json")
ROWS = [q for q in QUESTIONS if q.expect == "rows"]


def test_seventy_intents() -> None:
    assert [q.id for q in QUESTIONS] == [f"q{i:03d}" for i in range(1, 71)]


def test_tier_composition() -> None:
    test = Counter(q.tier for q in QUESTIONS if q.split == "test")
    dev = Counter(q.tier for q in QUESTIONS if q.split == "dev")
    assert test == {"T1": 12, "T2": 16, "T3": 16, "T4": 11, "A": 5}
    assert dev == {"T1": 2, "T2": 2, "T3": 3, "T4": 2, "A": 1}


def test_item_counts() -> None:
    assert len(build_items(QUESTIONS, "test", ("de", "en"))) == 120
    assert len(build_items(QUESTIONS, "dev", ("de", "en"))) == 20


@pytest.mark.parametrize("q", ROWS, ids=lambda q: q.id)
def test_gold_and_check_bind_to_schema(q: Question) -> None:
    assert unknown_columns(q.gold_sql, SCHEMA) == []
    assert unknown_columns(q.check_sql, SCHEMA) == []


@pytest.mark.parametrize("q", ROWS, ids=lambda q: q.id)
def test_check_is_not_a_copy(q: Question) -> None:
    assert " ".join(q.gold_sql.split()).lower() != " ".join(q.check_sql.split()).lower()


def test_unknown_column_is_reported() -> None:
    problems = unknown_columns("SELECT erzeugung_gwh FROM dw.fact_erzeugung", SCHEMA)
    assert problems and "erzeugung_gwh" in problems[0]


def test_unknown_table_is_reported_and_ctes_are_not() -> None:
    assert unknown_columns("SELECT 1 AS a FROM dw.fact_erzeugungen", SCHEMA) == [
        "Unknown table: dw.fact_erzeugungen"
    ]
    assert unknown_columns("WITH t AS (SELECT 1 AS a) SELECT a FROM t", SCHEMA) == []
