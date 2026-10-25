import datetime as dt
from decimal import Decimal

from energie_sql_bench.config import SnapshotSettings
from energie_sql_bench.snapshot import compare_fingerprints, compute_fingerprint, fingerprint_digest

SNAP = SnapshotSettings("2026-10-01", "2023-01-01", "2026-09-30", "2026-09", "2026-10-25", "abc123")


def make_fetch(erzeugung_sum: str = "100.500"):
    def fetch(sql: str, params: tuple = ()) -> list[tuple]:
        if "MIN(ts_utc)" in sql:
            assert params == (20230101, 20260930)
            return [(dt.datetime(2022, 12, 31, 23, 0), dt.datetime(2026, 9, 30, 21, 45))]
        if "fact_kapazitaet" in sql:
            assert params == (20260901,)
            return [(202609, 10, Decimal("1.000"), Decimal("0.000"), Decimal("50.000"))]
        if "fact_erzeugung" in sql:
            return [(202301, 35712, 35700, Decimal(erzeugung_sum))]
        if "fact_last" in sql:
            return [(202301, 2976, Decimal("1"), Decimal("2"), Decimal("3"))]
        if "fact_preis" in sql:
            return [(202301, 744, 744, Decimal("99.10"))]
        raise AssertionError(sql)

    return fetch


def test_fingerprint_structure_and_digest() -> None:
    fp = compute_fingerprint(make_fetch(), SNAP)
    assert fp["cut"] == {"smard_start": "2023-01-01", "smard_end": "2026-09-30", "mastr_end": "2026-09"}
    assert fp["facts"]["fact_erzeugung"] == [[202301, 35712, 35700, "100.500"]]
    assert fp["range"]["max_ts_utc"] == "2026-09-30T21:45:00"
    assert fp["mastr_export"] == "2026-10-25" and fp["monitor_commit"] == "abc123"
    assert fp["digest"] == fingerprint_digest(fp)
    assert len(fp["digest"]) == 16


def test_compare_detects_changed_month() -> None:
    stored = compute_fingerprint(make_fetch(), SNAP)
    live = compute_fingerprint(make_fetch("100.600"), SNAP)
    diffs = compare_fingerprints(stored, live)
    assert len(diffs) == 1 and "fact_erzeugung" in diffs[0] and "202301" in diffs[0]
    assert compare_fingerprints(stored, compute_fingerprint(make_fetch(), SNAP)) == []
