from pathlib import Path

from energie_sql_bench.config import load_settings
from energie_sql_bench.files import read_json
from energie_sql_bench.guard import check_sql
from energie_sql_bench.schema import unknown_columns
from energie_sql_bench.semantic import load_semantic, render_semantic

REPO = Path(__file__).resolve().parents[2]
LAYER = load_semantic(REPO / "semantic" / "measures.yaml")
VALUES = {
    "{von}": "20240101",
    "{bis}": "20241231",
    "{von_vorjahr}": "20230101",
    "{bis_vorjahr}": "20231231",
    "{jahr}": "2024",
    "{monat}": "2024-12",
    "{vormonat}": "2024-11",
    "{monatserster}": "20241201",
    "{et}": "Photovoltaik",
}


def fill(sql: str) -> str:
    for key, value in VALUES.items():
        sql = sql.replace(key, value)
    return sql


def test_twenty_six_unique_measures() -> None:
    assert len(LAYER.measures) == 26
    assert len({m.id for m in LAYER.measures}) == 26


def test_source_commit_matches_snapshot() -> None:
    assert LAYER.source_commit == load_settings(REPO, environ={}).snapshot.monitor_commit


def test_templates_are_allowed_and_bind() -> None:
    schema = read_json(REPO / "schema" / "schema.json")
    for measure in LAYER.measures:
        sql = fill(measure.sql)
        assert "{" not in sql, measure.id
        assert check_sql(sql).allowed, measure.id
        assert unknown_columns(sql, schema) == [], measure.id


def test_render_contains_rules_synonyms_and_measures() -> None:
    text = render_semantic(LAYER)
    assert text == render_semantic(LAYER)
    assert "Rules:" in text and "Synonyms" in text and "Measures" in text
    assert "- börsenstrompreis -> Day-Ahead-Preis" in text
    assert "Volllaststunden (h) / Full-load hours (h) [hours]" in text
    measure_lines = text.split("Measures", 1)[1].splitlines()[1:]
    assert len(measure_lines) == 26 and all(line.startswith("- ") for line in measure_lines)
