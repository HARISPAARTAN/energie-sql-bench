import pytest
from pydantic import ValidationError

from energie_sql_bench.config import CompareSettings
from energie_sql_bench.questions import Question, build_items, ngram_jaccard, tables_in_sql, tolerance_for

BASE = {
    "id": "q001",
    "split": "test",
    "tier": "T1",
    "de": "Wie hoch war der Preis?",
    "en": "What was the price?",
    "expect": "rows",
    "gold_sql": "SELECT AVG(day_ahead_eur_mwh) FROM dw.fact_preis",
    "check_sql": "SELECT AVG(day_ahead_eur_mwh) FROM rpt.v_preis",
    "tables": ["dw.fact_preis"],
    "notes": "Test",
}


def test_valid_question_and_items() -> None:
    q = Question.model_validate(BASE)
    assert q.text("de").startswith("Wie") and q.duckdb_ok
    items = build_items([q], "test", ("de", "en"))
    assert [i.item_id for i in items] == ["q001-de", "q001-en"]
    assert items[1].text == "What was the price?"
    assert build_items([q], "dev", ("de",)) == []
    assert len(build_items([q], "all", ("de",))) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"tier": "A"},
        {"check_sql": None},
        {"expect": "abstain"},
        {"duckdb": "skip:"},
        {"en": "Wie hoch war der Preis?"},
        {"id": "x1"},
        {"unknown": 1},
    ],
)
def test_invalid_questions(change: dict) -> None:
    with pytest.raises(ValidationError):
        Question.model_validate({**BASE, **change})


def test_abstain_question() -> None:
    q = Question.model_validate(
        {**BASE, "tier": "A", "expect": "abstain", "gold_sql": None, "check_sql": None, "tables": []}
    )
    assert q.expect == "abstain"


def test_tables_in_sql_skips_ctes() -> None:
    sql = "WITH t AS (SELECT * FROM dw.fact_preis) SELECT * FROM t JOIN DW.Dim_Region r ON 1 = 1"
    assert tables_in_sql(sql) == ["dw.dim_region", "dw.fact_preis"]


def test_tolerance_override() -> None:
    q = Question.model_validate({**BASE, "tolerance": {"rel": 0.01, "abs": 1.0}})
    assert tolerance_for(q, CompareSettings(1e-4, 0.005)) == (0.01, 1.0)
    assert tolerance_for(Question.model_validate(BASE), CompareSettings(1e-4, 0.005)) == (1e-4, 0.005)


def test_ngram_jaccard() -> None:
    assert ngram_jaccard("a b c d", "a b c d") == 1.0
    assert ngram_jaccard("a b c d", "x y z w") == 0.0
    assert ngram_jaccard("a b", "a b") == 0.0
