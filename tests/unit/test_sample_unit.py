from energie_sql_bench.sample import (
    EXPECTED_ROWS,
    SAMPLE_TABLES,
    ParityRow,
    duck_type,
    parity_summary,
    render_parity,
    sample_where,
)


def test_duck_types() -> None:
    assert duck_type("decimal(12,3)") == "DECIMAL(12,3)"
    assert duck_type("datetime2(0)") == "TIMESTAMP"
    assert duck_type("time(0)") == "TIME"
    assert duck_type("date") == "DATE"
    assert duck_type("bit") == "BOOLEAN"
    assert duck_type("tinyint") == "SMALLINT"
    assert duck_type("char(3)") == "VARCHAR"
    assert duck_type("nvarchar(40)") == "VARCHAR"


def test_sample_filters() -> None:
    assert (
        sample_where("fact_preis")
        == "(datum_key BETWEEN 20250609 AND 20250615 OR datum_key BETWEEN 20251020 AND 20251026)"
    )
    assert sample_where("fact_kapazitaet") == "datum_key IN (20260701, 20260801, 20260901)"
    assert sample_where("dim_datum") == "datum_key BETWEEN 20250101 AND 20261231"
    assert sample_where("dim_region") == "1 = 1"
    assert set(EXPECTED_ROWS) == set(SAMPLE_TABLES)


def test_parity_summary_and_render() -> None:
    rows = [
        ParityRow("q001", "match", "ok", False),
        ParityRow("q002", "match", "ok", True),
        ParityRow("q003", "skip", "FORMAT ohne Gegenstück", False),
        ParityRow("q004", "mismatch", "Werte stimmen nicht überein", True),
    ]
    summary = parity_summary(rows)
    assert summary["intents"] == 4 and summary["matched"] == 2 and summary["coverage"] == 0.5
    assert summary["matched_nontrivial"] == 1 and summary["skipped"] == 1 and summary["mismatched"] == 1
    text = render_parity(summary)
    assert "| q003 | skip | FORMAT ohne Gegenstück |" in text
    assert "50.0 %" in text
