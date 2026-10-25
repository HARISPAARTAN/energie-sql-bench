from pathlib import Path

import pytest

from energie_sql_bench.sample import EXPECTED_ROWS, load_duckdb

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample"
VIEW_ROWS = {
    "v_dim_datum": 730,
    "v_dim_zeit": 96,
    "v_dim_energietraeger": 12,
    "v_dim_region": 5,
    "v_dim_bundesland": 18,
    "v_erzeugung": 14828,
    "v_last": 1348,
    "v_preis": 337,
    "v_last_stunde": 337,
    "v_preis_last_stunde": 337,
    "v_negative_preisphasen": 10,
    "v_kapazitaet": 456,
}


@pytest.fixture(scope="module")
def con():  # noqa: ANN201
    c = load_duckdb(SAMPLE)
    yield c
    c.close()


@pytest.mark.parametrize(("table", "rows"), sorted(EXPECTED_ROWS.items()))
def test_table_rows(con, table: str, rows: int) -> None:  # noqa: ANN001
    assert con.execute(f"SELECT COUNT(*) FROM dw.{table}").fetchone()[0] == rows


@pytest.mark.parametrize(("view", "rows"), sorted(VIEW_ROWS.items()))
def test_view_rows(con, view: str, rows: int) -> None:  # noqa: ANN001
    assert con.execute(f"SELECT COUNT(*) FROM rpt.{view}").fetchone()[0] == rows


def test_clock_change_day(con) -> None:  # noqa: ANN001
    assert (
        con.execute("SELECT viertelstunden FROM dw.dim_datum WHERE datum_key = 20251026").fetchone()[0] == 100
    )
    assert con.execute("SELECT COUNT(*) FROM dw.fact_preis WHERE datum_key = 20251026").fetchone()[0] == 25


def test_negative_phases_in_local_time(con) -> None:  # noqa: ANN001
    assert con.execute(
        "SELECT COUNT(*), SUM(stunden), MAX(stunden) FROM rpt.v_negative_preisphasen"
    ).fetchone() == (
        10,
        53,
        8,
    )
    start, end = con.execute(
        "SELECT start_lokal, ende_lokal FROM rpt.v_negative_preisphasen WHERE start_datum_key = 20251026"
    ).fetchone()
    assert (str(start), str(end)) == ("2025-10-26 08:00:00", "2025-10-26 16:00:00")


def test_codes_are_trimmed_and_capacity_matches_warehouse(con) -> None:  # noqa: ANN001
    assert con.execute("SELECT kuerzel FROM dw.dim_bundesland WHERE bundesland_key = 2").fetchone()[0] == "BY"
    total = con.execute(
        "SELECT SUM(k.bestand_mw) FROM dw.fact_kapazitaet k JOIN dw.dim_energietraeger e "
        "ON e.energietraeger_key = k.energietraeger_key WHERE k.datum_key = 20260901 AND e.name_de = 'Wind Offshore'"
    ).fetchone()[0]
    assert str(total) == "11598.743"
