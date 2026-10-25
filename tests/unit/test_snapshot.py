import datetime as dt
from decimal import Decimal

import pytest

from energie_sql_bench.config import SnapshotSettings
from energie_sql_bench.snapshot import (
    compare_fingerprints,
    compute_fingerprint,
    digest_problem,
    fingerprint_digest,
    view_hash,
)

SNAP = SnapshotSettings("2026-10-01", "2023-01-01", "2026-09-30", "2026-09", "2026-10-25", "abc123")

DIMS = {
    "dw.dim_bundesland": [(1, "Baden-Württemberg"), (2, "Bayern")],
    "dw.dim_datum": [(20230101, "2023-01-01")],
    "dw.dim_energietraeger": [(1, "Photovoltaik", "Erneuerbar"), (2, "Wind Onshore", "Erneuerbar")],
    "dw.dim_region": [(1, "DE-LU")],
    "dw.dim_zeit": [(0, "00:00")],
}


def make_fetch(
    pv: str = "60.500",
    wind: str = "40.000",
    kap_by_state: tuple[str, str] = ("30.000", "20.000"),
    carrier: str = "Photovoltaik",
    view: str = "SELECT 1",
):
    """Fake database: the two carriers add up to 100.500, the two states to 50.000."""
    dims = {**DIMS, "dw.dim_energietraeger": [(1, carrier, "Erneuerbar"), (2, "Wind Onshore", "Erneuerbar")]}

    def fetch(sql: str, params: tuple = ()) -> list[tuple]:
        if "MIN(ts_utc), MAX(ts_utc)" in sql:
            assert params == (20230101, 20260930)
            return [(dt.datetime(2022, 12, 31, 23, 0), dt.datetime(2026, 9, 30, 21, 45))]
        if "sys.sql_modules" in sql:
            return [("rpt.v_preis", view)]
        if sql.startswith("SELECT * FROM "):
            name = sql.split()[3]
            return dims[name]
        if "COUNT(*), MAX(datum_key)" in sql:
            table = sql.split(" FROM ")[1].split()[0]
            assert params == ((20260901,) if table == "dw.fact_kapazitaet" else (20230101, 20260930))
            return [
                (10, 20260930, dt.datetime(2026, 9, 30, 21, 45) if table != "dw.fact_kapazitaet" else None)
            ]
        if "FROM dw.fact_kapazitaet" in sql:
            assert params == (20230101, 20260901)
            # (monat, bundesland_key, energietraeger_key, zeilen, zubau, anzahl_zubau, abgang, anzahl_abgang,
            #  anfangsbestand, bestand, bestand_anzahl): per carrier, then per Bundesland
            by_state = [
                (
                    202609,
                    1,
                    None,
                    5,
                    Decimal("1"),
                    1,
                    Decimal("0"),
                    0,
                    Decimal("0"),
                    Decimal(kap_by_state[0]),
                    9,
                ),
                (
                    202609,
                    2,
                    None,
                    5,
                    Decimal("1"),
                    1,
                    Decimal("0"),
                    0,
                    Decimal("0"),
                    Decimal(kap_by_state[1]),
                    9,
                ),
            ]
            return [
                (202609, None, 1, 10, Decimal("2"), 2, Decimal("0"), 0, Decimal("0"), Decimal("50"), 18),
                *by_state,
            ]
        if "FROM dw.fact_erzeugung" in sql:
            return [
                (202301, 1, 1, 17856, 17856, Decimal(pv)),
                (202301, 1, 2, 17856, 17844, Decimal(wind)),
            ]
        if "FROM dw.fact_last" in sql:
            return [(202301, 1, 2976, 2976, Decimal("1"), 2976, Decimal("2"), 2900, Decimal("3"))]
        if "FROM dw.fact_preis" in sql:
            return [(202301, 1, 744, 744, Decimal("99.10"))]
        raise AssertionError(sql)

    return fetch


def test_fingerprint_structure_and_digest() -> None:
    fp = compute_fingerprint(make_fetch(), SNAP)
    assert fp["cut"] == {"smard_start": "2023-01-01", "smard_end": "2026-09-30", "mastr_end": "2026-09"}
    assert fp["facts"]["fact_erzeugung"][0] == [202301, 1, 1, 17856, 17856, "60.500"]
    assert fp["facts"]["fact_last"] == [[202301, 1, 2976, 2976, "1", 2976, "2", 2900, "3"]]
    assert [row[:3] for row in fp["facts"]["fact_kapazitaet"]] == [
        [202609, None, 1],
        [202609, 1, None],
        [202609, 2, None],
    ]
    assert fp["range"]["max_ts_utc"] == "2026-09-30T21:45:00"
    assert fp["tables"]["dw.fact_erzeugung"] == {
        "rows": 10,
        "max_key": 20260930,
        "max_ts_utc": "2026-09-30T21:45:00",
    }
    assert (
        fp["tables"]["dw.dim_energietraeger"]["rows"] == 2
        and fp["tables"]["dw.dim_energietraeger"]["max_key"] == 2
    )
    assert len(fp["tables"]["dw.dim_region"]["sha256"]) == 64
    assert fp["views"] == {"rpt.v_preis": view_hash("SELECT 1")}
    assert fp["mastr_export"] == "2026-10-25" and fp["monitor_commit"] == "abc123"
    assert fp["digest"] == fingerprint_digest(fp)
    assert len(fp["digest"]) == 16


def test_compare_detects_changed_month() -> None:
    stored = compute_fingerprint(make_fetch(), SNAP)
    live = compute_fingerprint(make_fetch(pv="60.600"), SNAP)
    diffs = compare_fingerprints(stored, live)
    assert len(diffs) == 1 and "fact_erzeugung" in diffs[0] and "202301" in diffs[0]
    assert compare_fingerprints(stored, compute_fingerprint(make_fetch(), SNAP)) == []


def test_redistribution_between_carriers_with_equal_total_is_detected() -> None:
    stored = compute_fingerprint(make_fetch(), SNAP)
    live = compute_fingerprint(make_fetch(pv="50.500", wind="50.000"), SNAP)  # still 100.500 in total
    assert live["digest"] != stored["digest"]
    diffs = compare_fingerprints(stored, live)
    assert len(diffs) == 2 and all("fact_erzeugung" in d for d in diffs)


def test_redistribution_between_states_with_equal_total_is_detected() -> None:
    stored = compute_fingerprint(make_fetch(), SNAP)
    live = compute_fingerprint(make_fetch(kap_by_state=("25.000", "25.000")), SNAP)
    assert live["digest"] != stored["digest"]
    diffs = compare_fingerprints(stored, live)
    assert len(diffs) == 2 and all("fact_kapazitaet" in d for d in diffs)


def test_dimension_rename_is_detected() -> None:
    stored = compute_fingerprint(make_fetch(), SNAP)
    live = compute_fingerprint(make_fetch(carrier="Solar"), SNAP)
    assert live["digest"] != stored["digest"]
    diffs = compare_fingerprints(stored, live)
    assert len(diffs) == 1 and "dw.dim_energietraeger" in diffs[0]


def test_view_definition_change_is_detected_and_line_endings_are_not() -> None:
    stored = compute_fingerprint(make_fetch(view="SELECT 1\nFROM t"), SNAP)
    assert (
        compare_fingerprints(stored, compute_fingerprint(make_fetch(view="SELECT 1\r\nFROM t "), SNAP)) == []
    )
    live = compute_fingerprint(make_fetch(view="SELECT 2\nFROM t"), SNAP)
    diffs = compare_fingerprints(stored, live)
    assert len(diffs) == 1 and "rpt.v_preis" in diffs[0]


def test_stored_digest_must_match_its_content() -> None:
    stored = compute_fingerprint(make_fetch(), SNAP)
    assert digest_problem(stored) is None
    stored["facts"]["fact_preis"][0][4] = "1.00"  # hand edit, digest left stale
    assert "passt nicht" in (digest_problem(stored) or "")
    assert any(
        "passt nicht" in d for d in compare_fingerprints(stored, compute_fingerprint(make_fetch(), SNAP))
    )
    assert "unvollständig" in (digest_problem({"digest": "x"}) or "")


def test_config_changes_outside_the_database_are_reported() -> None:
    stored = compute_fingerprint(make_fetch(), SNAP)
    other = SnapshotSettings("2026-10-01", "2023-01-01", "2026-09-30", "2026-09", "2026-11-01", "def456")
    diffs = compare_fingerprints(stored, compute_fingerprint(make_fetch(), other))
    assert {d.split(":")[0] for d in diffs} == {"mastr_export", "monitor_commit"}


@pytest.mark.parametrize("fact", ["fact_erzeugung", "fact_last", "fact_preis", "fact_kapazitaet"])
def test_every_fact_is_in_the_digest(fact: str) -> None:
    fp = compute_fingerprint(make_fetch(), SNAP)
    assert fact in fp["facts"] and fact in " ".join(fp["tables"])
