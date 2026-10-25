"""Fingerprint of the data cut: row counts and SUM checksums per fact and month, plus the time range."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from energie_sql_bench.config import SnapshotSettings
from energie_sql_bench.resultset import encode_value

Fetch = Callable[..., list[tuple]]

FACT_QUERIES = {
    "fact_erzeugung": (
        "SELECT datum_key / 100 AS monat, COUNT(*) AS zeilen, COUNT(erzeugung_mwh) AS werte, "
        "SUM(erzeugung_mwh) AS summe FROM dw.fact_erzeugung WHERE datum_key BETWEEN ? AND ? "
        "GROUP BY datum_key / 100 ORDER BY monat"
    ),
    "fact_last": (
        "SELECT datum_key / 100 AS monat, COUNT(*) AS zeilen, SUM(netzlast_mwh) AS netzlast, "
        "SUM(residuallast_mwh) AS residuallast, SUM(pumpspeicher_verbrauch_mwh) AS pumpspeicher "
        "FROM dw.fact_last WHERE datum_key BETWEEN ? AND ? GROUP BY datum_key / 100 ORDER BY monat"
    ),
    "fact_preis": (
        "SELECT datum_key / 100 AS monat, COUNT(*) AS zeilen, COUNT(day_ahead_eur_mwh) AS werte, "
        "SUM(day_ahead_eur_mwh) AS summe FROM dw.fact_preis WHERE datum_key BETWEEN ? AND ? "
        "GROUP BY datum_key / 100 ORDER BY monat"
    ),
}
KAPAZITAET_SQL = (
    "SELECT datum_key / 100 AS monat, COUNT(*) AS zeilen, SUM(zubau_mw) AS zubau, SUM(abgang_mw) AS abgang, "
    "SUM(bestand_mw) AS bestand FROM dw.fact_kapazitaet WHERE datum_key <= ? GROUP BY datum_key / 100 ORDER BY monat"
)
RANGE_SQL = "SELECT MIN(ts_utc), MAX(ts_utc) FROM dw.fact_erzeugung WHERE datum_key BETWEEN ? AND ?"


def _encode(rows: list[tuple]) -> list[list[Any]]:
    return [[encode_value(v) for v in row] for row in rows]


def fingerprint_digest(fp: dict[str, Any]) -> str:
    core = {key: fp[key] for key in ("cut", "facts", "range")}
    return hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[
        :16
    ]


def compute_fingerprint(fetch: Fetch, snap: SnapshotSettings) -> dict[str, Any]:
    window = (snap.smard_start_key, snap.smard_end_key)
    facts = {name: _encode(fetch(sql, window)) for name, sql in FACT_QUERIES.items()}
    facts["fact_kapazitaet"] = _encode(fetch(KAPAZITAET_SQL, (snap.mastr_end_key,)))
    low, high = fetch(RANGE_SQL, window)[0]
    fp: dict[str, Any] = {
        "cut": {"smard_start": snap.smard_start, "smard_end": snap.smard_end, "mastr_end": snap.mastr_end},
        "facts": facts,
        "range": {"min_ts_utc": encode_value(low), "max_ts_utc": encode_value(high)},
    }
    fp["digest"] = fingerprint_digest(fp)
    fp["mastr_export"] = snap.mastr_export
    fp["monitor_commit"] = snap.monitor_commit
    return fp


def compare_fingerprints(stored: dict[str, Any], live: dict[str, Any]) -> list[str]:
    diffs: list[str] = []
    if stored.get("cut") != live.get("cut"):
        diffs.append(f"Datenschnitt: gespeichert {stored.get('cut')} / live {live.get('cut')}")
    if stored.get("range") != live.get("range"):
        diffs.append(f"Zeitbereich: gespeichert {stored.get('range')} / live {live.get('range')}")
    stored_facts, live_facts = stored.get("facts", {}), live.get("facts", {})
    for fact in sorted(set(stored_facts) | set(live_facts)):
        a = {row[0]: row for row in stored_facts.get(fact, [])}
        b = {row[0]: row for row in live_facts.get(fact, [])}
        for month in sorted(set(a) | set(b)):
            if a.get(month) != b.get(month):
                diffs.append(f"{fact} Monat {month}: gespeichert {a.get(month)} / live {b.get(month)}")
    return diffs
