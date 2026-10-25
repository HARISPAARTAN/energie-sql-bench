import os
from pathlib import Path

import pytest

from energie_sql_bench.config import load_settings
from energie_sql_bench.files import read_json, write_json, write_text
from energie_sql_bench.prompts import (
    ABSTAIN_TOKEN,
    build_prompt,
    extract_sql,
    load_prompt_context,
    repair_prompt,
    select_tables,
)
from energie_sql_bench.questions import Item, load_questions

REPO = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).resolve().parent / "golden"
SETTINGS = load_settings(REPO, environ={})
QUESTIONS = {q.id: q for q in load_questions(REPO / "bench" / "questions")}
CTX = load_prompt_context(SETTINGS, list(QUESTIONS.values()))
UPDATE = os.environ.get("ESB_UPDATE_GOLDEN") == "1"


def item(qid: str, lang: str) -> Item:
    return Item(QUESTIONS[qid], lang)


@pytest.mark.parametrize(
    ("text", "sql", "abstained", "error"),
    [
        ("Hier:\n```sql\nSELECT 1 AS a\n```\nFertig.", "SELECT 1 AS a", False, None),
        ("```SQL\nSELECT 2\n```", "SELECT 2", False, None),
        ("```tsql\nSELECT 3;\n```", "SELECT 3;", False, None),
        ("```\nSELECT 4\n```", "SELECT 4", False, None),
        (ABSTAIN_TOKEN, None, True, None),
        (f"Das geht nicht. {ABSTAIN_TOKEN}", None, True, None),
        ("```sql\nSELECT 1\n```\n```sql\nSELECT 2\n```", None, False, "mehrere SQL-Blöcke"),
        ("SELECT 1", None, False, "kein SQL-Block"),
        ("", None, False, "kein SQL-Block"),
    ],
)
def test_extract_sql(text: str, sql: str | None, abstained: bool, error: str | None) -> None:
    result = extract_sql(text)
    assert (result.sql, result.abstained, result.error) == (sql, abstained, error)


def test_variant_sections() -> None:
    v = SETTINGS.variants
    p1 = build_prompt(item("q001", "de"), v["v1"], CTX).system
    p2 = build_prompt(item("q001", "de"), v["v2"], CTX).system
    p3 = build_prompt(item("q001", "de"), v["v3"], CTX).system
    assert "## Semantic layer" not in p1 and "## Examples" not in p1
    assert "## Examples" in p2 and "## Semantic layer" not in p2
    assert "## Semantic layer" in p3 and "## Examples" not in p3
    assert "dw.fact_kapazitaet" in p1


def test_oracle_and_retrieved_tables() -> None:
    v = SETTINGS.variants
    assert select_tables(item("q001", "de"), v["v4"], CTX) is None
    assert select_tables(item("q001", "de"), v["v5"], CTX) == ["dw.dim_region", "dw.fact_preis"]
    assert select_tables(item("q010", "de"), v["v5"], CTX) is None
    retrieved = select_tables(item("q016", "de"), v["v6"], CTX)
    assert "dw.fact_preis" in retrieved
    oracle_system = build_prompt(item("q001", "de"), v["v5"], CTX).system
    schema_part = oracle_system.split("## Schema", 1)[1].split("## Semantic layer", 1)[0]
    assert "dw.fact_preis (table)" in schema_part
    assert "dw.fact_kapazitaet (table)" not in schema_part


def test_user_message_and_language() -> None:
    v4 = SETTINGS.variants["v4"]
    de = build_prompt(item("q001", "de"), v4, CTX)
    en = build_prompt(item("q001", "en"), v4, CTX)
    assert de.system == en.system
    assert de.messages == (("user", "Frage: " + QUESTIONS["q001"].de),)
    assert en.messages[0][1].startswith("Question: ")
    assert de.hash != en.hash


def test_hash_stable_and_variant_sensitive() -> None:
    v = SETTINGS.variants
    a = build_prompt(item("q005", "en"), v["v4"], CTX)
    b = build_prompt(item("q005", "en"), v["v4"], CTX)
    assert a.hash == b.hash and len(a.hash) == 16
    assert a.hash != build_prompt(item("q005", "en"), v["v3"], CTX).hash


def test_repair_prompt_appends_turns() -> None:
    p = build_prompt(item("q001", "de"), SETTINGS.variants["v4"], CTX)
    r = repair_prompt(p, "```sql\nSELECT x\n```", "Invalid column name 'x'.")
    assert r.system == p.system
    assert [role for role, _ in r.messages] == ["user", "assistant", "user"]
    assert "Invalid column name" in r.messages[2][1]
    assert r.hash != p.hash


def test_few_shot_uses_dev_examples_only() -> None:
    system = build_prompt(item("q001", "de"), SETTINGS.variants["v4"], CTX).system
    assert QUESTIONS["q063"].de in system
    assert QUESTIONS["q001"].de not in system


GOLDEN_CASES = [
    ("q001", "de", "v1"),
    ("q001", "de", "v4"),
    ("q005", "en", "v2"),
    ("q005", "en", "v3"),
    ("q008", "de", "v5"),
    ("q010", "en", "v6"),
    ("q027", "de", "v6"),
    ("q057", "en", "v5"),
]


def test_golden_prompt_hashes() -> None:
    actual = {
        f"{qid}-{lang}|{vid}": build_prompt(item(qid, lang), SETTINGS.variants[vid], CTX).hash
        for qid, lang, vid in GOLDEN_CASES
    }
    path = GOLDEN / "prompt_hashes.json"
    if UPDATE:
        write_json(path, actual)
    assert read_json(path) == actual


def test_golden_prompt_text() -> None:
    p = build_prompt(item("q005", "en"), SETTINGS.variants["v4"], CTX)
    text = "=== system ===\n" + p.system + "=== user ===\n" + p.messages[0][1] + "\n"
    path = GOLDEN / "prompt_v4_q005-en.txt"
    if UPDATE:
        write_text(path, text)
    assert path.read_text(encoding="utf-8") == text
