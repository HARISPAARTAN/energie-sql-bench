from pathlib import Path

import pytest

from energie_sql_bench.files import read_json
from energie_sql_bench.questions import Question, load_questions
from energie_sql_bench.schema import unknown_columns

REPO = Path(__file__).resolve().parents[2]
QUESTIONS = load_questions(REPO / "bench" / "questions")
SCHEMA = read_json(REPO / "schema" / "schema.json")
ROWS = [q for q in QUESTIONS if q.expect == "rows"]


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
