"""Fingerprint of the data cut.

What is hashed (all inside the cut, so later months appended by the monitor do not change it):

* ``facts``: per month and per carrier (generation), per region (load, price) and per carrier and per
  Bundesland (capacity) the row count, the non-null counts and the sums of every measure. A redistribution
  between carriers or states with an equal monthly total therefore changes the digest.
* ``tables``: row count and maximum key of every fact (inside the cut; capacity including its history before
  2023) and every dimension, plus a content hash of each dimension (names, categories, calendar attributes).
* ``views``: a hash of every ``rpt`` view definition (``sys.sql_modules``); the gold queries read these views.
* ``range`` and ``cut``.

One query per object.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from energie_sql_bench.config import SnapshotSettings
from energie_sql_bench.resultset import encode_value

Fetch = Callable[..., list[tuple]]

# Fact aggregates: (SQL, number of leading key columns). The key columns identify a row when two
# fingerprints are compared; everything after them is a count or a sum.
FACT_QUERIES: dict[str, tuple[str, int]] = {
    "fact_erzeugung": (
        "SELECT datum_key / 100 AS monat, region_key, energietraeger_key, COUNT(*) AS zeilen, "
        "COUNT(erzeugung_mwh) AS werte, SUM(erzeugung_mwh) AS summe "
        "FROM dw.fact_erzeugung WHERE datum_key BETWEEN ? AND ? "
        "GROUP BY datum_key / 100, region_key, energietraeger_key ORDER BY monat, region_key, energietraeger_key",
        3,
    ),
    "fact_last": (
        "SELECT datum_key / 100 AS monat, region_key, COUNT(*) AS zeilen, "
        "COUNT(netzlast_mwh) AS netzlast_werte, SUM(netzlast_mwh) AS netzlast, "
        "COUNT(residuallast_mwh) AS residuallast_werte, SUM(residuallast_mwh) AS residuallast, "
        "COUNT(pumpspeicher_verbrauch_mwh) AS pumpspeicher_werte, "
        "SUM(pumpspeicher_verbrauch_mwh) AS pumpspeicher "
        "FROM dw.fact_last WHERE datum_key BETWEEN ? AND ? "
        "GROUP BY datum_key / 100, region_key ORDER BY monat, region_key",
        2,
    ),
    "fact_preis": (
        "SELECT datum_key / 100 AS monat, region_key, COUNT(*) AS zeilen, COUNT(day_ahead_eur_mwh) AS werte, "
        "SUM(day_ahead_eur_mwh) AS summe FROM dw.fact_preis WHERE datum_key BETWEEN ? AND ? "
        "GROUP BY datum_key / 100, region_key ORDER BY monat, region_key",
        2,
    ),
    # Two groupings in one pass: per carrier (bundesland_key NULL) and per Bundesland (energietraeger_key NULL).
    "fact_kapazitaet": (
        "SELECT datum_key / 100 AS monat, bundesland_key, energietraeger_key, COUNT(*) AS zeilen, "
        "SUM(zubau_mw) AS zubau, SUM(anzahl_zubau) AS anzahl_zubau, SUM(abgang_mw) AS abgang, "
        "SUM(anzahl_abgang) AS anzahl_abgang, SUM(anfangsbestand_mw) AS anfangsbestand, "
        "SUM(bestand_mw) AS bestand, SUM(bestand_anzahl) AS bestand_anzahl "
        "FROM dw.fact_kapazitaet WHERE datum_key BETWEEN ? AND ? "
        "GROUP BY GROUPING SETS ((datum_key / 100, energietraeger_key), (datum_key / 100, bundesland_key)) "
        "ORDER BY monat, bundesland_key, energietraeger_key",
        3,
    ),
}
FACT_KEYS = {name: keys for name, (_, keys) in FACT_QUERIES.items()}

# Row count and maximum key per fact inside the cut (SMARD facts by datum_key window, capacity by month).
TABLE_QUERIES = {
    "dw.fact_erzeugung": "SELECT COUNT(*), MAX(datum_key), MAX(ts_utc) FROM dw.fact_erzeugung WHERE datum_key BETWEEN ? AND ?",
    "dw.fact_last": "SELECT COUNT(*), MAX(datum_key), MAX(ts_utc) FROM dw.fact_last WHERE datum_key BETWEEN ? AND ?",
    "dw.fact_preis": "SELECT COUNT(*), MAX(datum_key), MAX(ts_utc) FROM dw.fact_preis WHERE datum_key BETWEEN ? AND ?",
    "dw.fact_kapazitaet": "SELECT COUNT(*), MAX(datum_key), NULL FROM dw.fact_kapazitaet WHERE datum_key <= ?",
}
# Dimension tables with their key column: row count, maximum key and a content hash.
DIMENSIONS = {
    "dw.dim_bundesland": "bundesland_key",
    "dw.dim_datum": "datum_key",
    "dw.dim_energietraeger": "energietraeger_key",
    "dw.dim_region": "region_key",
    "dw.dim_zeit": "zeit_key",
}
VIEWS_SQL = (
    "SELECT SCHEMA_NAME(v.schema_id) + '.' + v.name AS name, m.definition "
    "FROM sys.views v JOIN sys.sql_modules m ON m.object_id = v.object_id "
    "WHERE SCHEMA_NAME(v.schema_id) = 'rpt' ORDER BY name"
)
RANGE_SQL = "SELECT MIN(ts_utc), MAX(ts_utc) FROM dw.fact_erzeugung WHERE datum_key BETWEEN ? AND ?"
DIGEST_KEYS = ("cut", "facts", "range", "tables", "views")


def _encode(rows: list[tuple]) -> list[list[Any]]:
    return [[encode_value(v) for v in row] for row in rows]


def _sha256(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def fingerprint_digest(fp: dict[str, Any]) -> str:
    return _sha256({key: fp[key] for key in DIGEST_KEYS})[:16]


def view_hash(definition: str) -> str:
    """Hash of a view definition; line endings are normalised so a re-deployment from Windows or Linux agrees."""
    text = definition.replace("\r\n", "\n").replace("\r", "\n").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def compute_fingerprint(fetch: Fetch, snap: SnapshotSettings) -> dict[str, Any]:
    window = (snap.smard_start_key, snap.smard_end_key)
    facts: dict[str, Any] = {}
    for name, (sql, _) in FACT_QUERIES.items():
        capacity_window = (
            snap.smard_start_key,
            snap.mastr_end_key,
        )  # history before the SMARD start is in `tables`
        facts[name] = _encode(fetch(sql, capacity_window if name == "fact_kapazitaet" else window))
    tables: dict[str, Any] = {}
    for name, sql in TABLE_QUERIES.items():
        params = (snap.mastr_end_key,) if name == "dw.fact_kapazitaet" else window
        count, max_key, max_ts = fetch(sql, params)[0]
        tables[name] = {"rows": count, "max_key": max_key, "max_ts_utc": encode_value(max_ts)}
    for name, key in DIMENSIONS.items():
        rows = fetch(f"SELECT * FROM {name} ORDER BY {key}")
        tables[name] = {
            "rows": len(rows),
            "max_key": rows[-1][0] if rows else None,
            "sha256": _sha256(_encode(rows)),
        }
    views = {name: view_hash(definition) for name, definition in fetch(VIEWS_SQL)}
    low, high = fetch(RANGE_SQL, window)[0]
    fp: dict[str, Any] = {
        "cut": {"smard_start": snap.smard_start, "smard_end": snap.smard_end, "mastr_end": snap.mastr_end},
        "facts": facts,
        "range": {"min_ts_utc": encode_value(low), "max_ts_utc": encode_value(high)},
        "tables": tables,
        "views": views,
    }
    fp["digest"] = fingerprint_digest(fp)
    fp["mastr_export"] = snap.mastr_export
    fp["monitor_commit"] = snap.monitor_commit
    return fp


def digest_problem(stored: dict[str, Any]) -> str | None:
    """A stored fingerprint whose digest does not match its own content was edited by hand or is incomplete."""
    try:
        expected = fingerprint_digest(stored)
    except KeyError as exc:
        return f"fingerprint.json unvollständig (Schlüssel {exc} fehlt): esb snapshot ausführen"
    if stored.get("digest") != expected:
        return f"Digest {stored.get('digest')} passt nicht zum Inhalt von fingerprint.json ({expected})"
    return None


def _by_key(rows: list[list[Any]], width: int) -> dict[tuple, list[Any]]:
    return {tuple(row[:width]): row for row in rows}


def compare_fingerprints(stored: dict[str, Any], live: dict[str, Any]) -> list[str]:
    diffs: list[str] = []
    problem = digest_problem(stored)
    if problem:
        diffs.append(problem)
    for field in ("cut", "range", "mastr_export", "monitor_commit"):
        if stored.get(field) != live.get(field):
            diffs.append(f"{field}: gespeichert {stored.get(field)} / live {live.get(field)}")
    stored_facts, live_facts = stored.get("facts", {}), live.get("facts", {})
    for fact in sorted(set(stored_facts) | set(live_facts)):
        width = FACT_KEYS.get(fact, 1)
        a = _by_key(stored_facts.get(fact, []), width)
        b = _by_key(live_facts.get(fact, []), width)
        for key in sorted(set(a) | set(b), key=lambda k: tuple(-1 if x is None else x for x in k)):
            if a.get(key) != b.get(key):
                diffs.append(f"{fact} {list(key)}: gespeichert {a.get(key)} / live {b.get(key)}")
    for section in ("tables", "views"):
        a_sec, b_sec = stored.get(section, {}), live.get(section, {})
        for name in sorted(set(a_sec) | set(b_sec)):
            if a_sec.get(name) != b_sec.get(name):
                diffs.append(f"{section} {name}: gespeichert {a_sec.get(name)} / live {b_sec.get(name)}")
    if not diffs and stored.get("digest") != live.get("digest"):
        diffs.append(f"Digest: gespeichert {stored.get('digest')} / live {live.get('digest')}")
    return diffs
