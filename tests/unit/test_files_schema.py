from pathlib import Path

from energie_sql_bench.files import dump_json, read_json, write_json
from energie_sql_bench.schema import dump_schema, render_schema, retrieve_tables, words


def fake_fetch(sql: str, params: tuple = ()) -> list[tuple]:
    if "INFORMATION_SCHEMA.TABLES" in sql:
        return [
            ("dw", "dim_region", "BASE TABLE"),
            ("dw", "fact_preis", "BASE TABLE"),
            ("rpt", "v_preis", "VIEW"),
        ]
    if "INFORMATION_SCHEMA.COLUMNS" in sql:
        return [
            ("dw", "dim_region", "region_key", "smallint", None, 5, 0, None, "NO"),
            ("dw", "dim_region", "smard_code", "nvarchar", 20, None, None, None, "NO"),
            ("dw", "fact_preis", "region_key", "smallint", None, 5, 0, None, "NO"),
            ("dw", "fact_preis", "ts_utc", "datetime2", None, None, None, 0, "NO"),
            ("dw", "fact_preis", "day_ahead_eur_mwh", "decimal", None, 9, 2, None, "YES"),
            ("rpt", "v_preis", "day_ahead_eur_mwh", "decimal", None, 9, 2, None, "YES"),
        ]
    if "PRIMARY KEY" in sql:
        return [
            ("dw", "dim_region", "region_key"),
            ("dw", "fact_preis", "region_key"),
            ("dw", "fact_preis", "ts_utc"),
        ]
    if "REFERENTIAL_CONSTRAINTS" in sql:
        return [("dw", "fact_preis", "region_key", "dw", "dim_region", "region_key")]
    if "dim_region" in sql:
        return [("DE-LU", "Marktgebiet Deutschland/Luxemburg", "Marktgebiet")]
    return []


DESCRIPTIONS = {
    "tables": {
        "dw.fact_preis": {"de": "Preis je Stunde", "en": "price per hour", "keywords": ["preis", "ahead"]},
        "dw.dim_region": {"de": "Regionen", "en": "regions", "keywords": ["region"]},
        "rpt.v_preis": {"de": "Sicht", "en": "view", "keywords": ["sicht"]},
    }
}


def test_dump_schema_structure() -> None:
    schema = dump_schema(fake_fetch, "energiewende")
    preis = schema["tables"]["dw.fact_preis"]
    assert schema["database"] == "energiewende"
    assert preis["type"] == "table"
    assert preis["columns"][1] == {"name": "ts_utc", "type": "datetime2(0)", "nullable": False}
    assert preis["columns"][2]["type"] == "decimal(9,2)"
    assert preis["primary_key"] == ["region_key", "ts_utc"]
    assert preis["foreign_keys"] == [{"column": "region_key", "references": "dw.dim_region.region_key"}]
    assert schema["tables"]["rpt.v_preis"]["type"] == "view"
    assert schema["tables"]["dw.dim_region"]["values"]["rows"][0][0] == "DE-LU"


def test_render_schema_is_deterministic_and_complete() -> None:
    schema = dump_schema(fake_fetch, "energiewende")
    text = render_schema(schema, DESCRIPTIONS)
    assert text == render_schema(schema, DESCRIPTIONS)
    assert "dw.fact_preis (table): Preis je Stunde / price per hour" in text
    assert "region_key smallint NOT NULL -> dw.dim_region.region_key" in text
    assert "primary key: region_key, ts_utc" in text
    only = render_schema(schema, DESCRIPTIONS, ["dw.dim_region"])
    assert "fact_preis" not in only


def test_retrieval_with_keywords_synonyms_and_fk_closure() -> None:
    schema = dump_schema(fake_fetch, "energiewende")
    assert retrieve_tables("Wie hoch war der Day-Ahead-Preis?", schema, DESCRIPTIONS, {}) == [
        "dw.dim_region",
        "dw.fact_preis",
    ]
    assert retrieve_tables(
        "Börsenstrompreis 2024", schema, DESCRIPTIONS, {"börsenstrompreis": "Day-Ahead-Preis"}
    ) == [
        "dw.dim_region",
        "dw.fact_preis",
    ]
    assert retrieve_tables("Wetter in Rom", schema, DESCRIPTIONS, {}) == sorted(schema["tables"])


def test_words_split_compounds() -> None:
    assert words("Photovoltaik-Leistung in DE-LU") == ["photovoltaik", "leistung", "in", "de", "lu"]


def test_json_files_are_sorted_with_lf(tmp_path: Path) -> None:
    path = tmp_path / "x" / "a.json"
    write_json(path, {"b": 1, "a": "ä"})
    assert path.read_bytes() == b'{\n  "a": "\xc3\xa4",\n  "b": 1\n}\n'
    assert read_json(path) == {"a": "ä", "b": 1}
    assert dump_json([1]) == "[\n  1\n]\n"
