from pathlib import Path

import pytest

from energie_sql_bench.files import read_json, read_yaml
from energie_sql_bench.gold import load_gold, sql_sha256
from energie_sql_bench.guard import check_sql
from energie_sql_bench.questions import Question, load_fewshot, load_questions, ngram_jaccard, tables_in_sql
from energie_sql_bench.snapshot import fingerprint_digest

REPO = Path(__file__).resolve().parents[2]
QUESTIONS = load_questions(REPO / "bench" / "questions")
GOLD = load_gold(REPO / "bench" / "gold")
SCHEMA = read_json(REPO / "schema" / "schema.json")
DESCRIPTIONS = read_yaml(REPO / "schema" / "descriptions.yaml")
FINGERPRINT = read_json(REPO / "snapshot" / "fingerprint.json")
FEWSHOT = load_fewshot(REPO / "bench" / "fewshot" / "fewshot.yaml", QUESTIONS)


def test_ids_are_unique() -> None:
    ids = [q.id for q in QUESTIONS]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("q", QUESTIONS, ids=lambda q: q.id)
def test_split_follows_id(q: Question) -> None:
    assert q.split == ("test" if int(q.id[1:]) <= 60 else "dev")


@pytest.mark.parametrize("q", QUESTIONS, ids=lambda q: q.id)
def test_gold_file_is_current(q: Question) -> None:
    entry = GOLD[q.id]
    assert entry.expect == q.expect
    if q.expect == "rows":
        assert entry.sql_sha256 == sql_sha256(q.gold_sql)
        assert entry.result is not None and entry.result.rows


@pytest.mark.parametrize("q", [q for q in QUESTIONS if q.expect == "rows"], ids=lambda q: q.id)
def test_tables_known_and_derived(q: Question) -> None:
    assert set(q.tables) <= set(SCHEMA["tables"])
    assert sorted(q.tables) == tables_in_sql(q.gold_sql)


@pytest.mark.parametrize("q", [q for q in QUESTIONS if q.expect == "rows"], ids=lambda q: q.id)
def test_guard_allows_gold_and_check(q: Question) -> None:
    assert check_sql(q.gold_sql).allowed
    assert check_sql(q.check_sql).allowed


def test_fingerprint_digest_matches_its_content() -> None:
    assert FINGERPRINT["digest"] == fingerprint_digest(FINGERPRINT)


@pytest.mark.parametrize("q", QUESTIONS, ids=lambda q: q.id)
def test_gold_was_frozen_against_the_committed_snapshot(q: Question) -> None:
    assert GOLD[q.id].snapshot == FINGERPRINT["digest"]


def test_fewshot_is_six_dev_intents() -> None:
    assert len(FEWSHOT) == 6
    assert all(q.split == "dev" for q in FEWSHOT)


def test_fewshot_has_no_near_duplicate_test_item() -> None:
    tests = [q for q in QUESTIONS if q.split == "test"]
    for example in FEWSHOT:
        for item in tests:
            for lang in ("de", "en"):
                assert ngram_jaccard(example.text(lang), item.text(lang)) < 0.5, (example.id, item.id, lang)


def test_committed_schema_has_all_objects() -> None:
    assert len(SCHEMA["tables"]) == 22
    assert sum(len(t["foreign_keys"]) for t in SCHEMA["tables"].values()) == 13


def test_descriptions_cover_the_schema() -> None:
    described = DESCRIPTIONS["tables"]
    assert sorted(described) == sorted(SCHEMA["tables"])
    for table, meta in described.items():
        columns = {c["name"] for c in SCHEMA["tables"][table]["columns"]}
        assert set(meta.get("columns", {})) <= columns, table
