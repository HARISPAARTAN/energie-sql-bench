"""CI sample: a slice of the warehouse as SQL Server database energiewende_sample, as Parquet and in DuckDB,
plus the gold-SQL parity check between the two engines."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from energie_sql_bench.compare import compare
from energie_sql_bench.config import CompareSettings, Settings
from energie_sql_bench.execute import (
    DuckDbExecutor,
    MssqlExecutor,
    admin_connect,
    connect_mssql,
    split_batches,
)
from energie_sql_bench.files import read_json
from energie_sql_bench.gold import GoldEntry, sql_sha256
from energie_sql_bench.questions import Question, tolerance_for
from energie_sql_bench.resultset import ResultSet, encode_value

SAMPLE_TABLES = (
    "dim_datum",
    "dim_zeit",
    "dim_energietraeger",
    "dim_region",
    "dim_bundesland",
    "fact_erzeugung",
    "fact_last",
    "fact_preis",
    "fact_kapazitaet",
)
EXPECTED_ROWS = {
    "dim_datum": 730,
    "dim_zeit": 96,
    "dim_energietraeger": 12,
    "dim_region": 5,
    "dim_bundesland": 18,
    "fact_erzeugung": 14828,
    "fact_last": 1348,
    "fact_preis": 337,
    "fact_kapazitaet": 456,
}
FACT_WHERE = "(datum_key BETWEEN 20250609 AND 20250615 OR datum_key BETWEEN 20251020 AND 20251026)"
WHERE = {
    "dim_datum": "datum_key BETWEEN 20250101 AND 20261231",
    "fact_kapazitaet": "datum_key IN (20260701, 20260801, 20260901)",
}


@dataclass(frozen=True)
class ParityRow:
    id: str
    status: str  # match | mismatch | error | skip | missing
    reason: str
    nontrivial: bool


def _is_zero(value: Any) -> bool:
    return isinstance(value, int | float | Decimal) and not isinstance(value, bool) and value == 0


def is_nontrivial(result: ResultSet) -> bool:
    """True when the result carries at least one value that is neither NULL nor a numeric zero. Empty results,
    all-NULL results and zero-only results prove little about a translation: both engines return nothing or 0."""
    return any(v is not None and not _is_zero(v) for row in result.rows for v in row)


def sample_where(table: str) -> str:
    return WHERE.get(table, FACT_WHERE if table.startswith("fact_") else "1 = 1")


def duck_type(sql_type: str) -> str:
    t = sql_type.lower()
    base = t.split("(")[0]
    if base in ("decimal", "numeric"):
        return t.upper()
    if base.startswith("datetime"):
        return "TIMESTAMP"
    return {
        "bigint": "BIGINT",
        "bit": "BOOLEAN",
        "date": "DATE",
        "float": "DOUBLE",
        "int": "INTEGER",
        "smallint": "SMALLINT",
        "time": "TIME",
        "tinyint": "SMALLINT",
    }.get(base, "VARCHAR")


def build_sample_db(settings: Settings, sa_password: str) -> dict[str, int]:
    """Recreate energiewende_sample from the warehouse (sa; the source database is only read)."""
    sample, source = settings.db.sample_name, settings.db.name
    if not sample.endswith("_sample") or sample == source:
        raise ValueError(f"Stichprobendatenbank muss auf _sample enden: {sample}")
    with admin_connect(settings.db, sa_password, "master") as con:
        con.execute(
            f"IF DB_ID(N'{sample}') IS NOT NULL BEGIN "
            f"ALTER DATABASE [{sample}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [{sample}]; END"
        )
        con.execute(f"CREATE DATABASE [{sample}]")
    counts: dict[str, int] = {}
    with admin_connect(settings.db, sa_password, sample) as con:
        con.execute("CREATE SCHEMA dw")
        con.execute("CREATE SCHEMA rpt")
        for table in SAMPLE_TABLES:
            con.execute(f"SELECT * INTO dw.{table} FROM [{source}].dw.{table} WHERE {sample_where(table)}")
            counts[table] = int(con.execute(f"SELECT COUNT(*) FROM dw.{table}").fetchone()[0])
        script = settings.path("sql/sample/030_views_mssql.sql").read_text(encoding="utf-8")
        for batch in split_batches(script):
            con.execute(batch)
    return counts


def _select_list(columns: list[dict[str, Any]]) -> str:
    return ", ".join(
        f"RTRIM({c['name']}) AS {c['name']}" if c["type"].startswith(("char", "nchar")) else c["name"]
        for c in columns
    )


def export_parquet(settings: Settings, out_dir: Path) -> dict[str, int]:
    """Read the sample as bench_reader and write one Parquet file per table (char columns right-trimmed)."""
    import duckdb

    schema = read_json(settings.path("schema/schema.json"))
    out_dir.mkdir(parents=True, exist_ok=True)
    source = connect_mssql(settings.db, settings.db.sample_name)
    duck = duckdb.connect()
    counts: dict[str, int] = {}
    try:
        for table in SAMPLE_TABLES:
            meta = schema["tables"][f"dw.{table}"]
            columns = meta["columns"]
            order = ", ".join(meta["primary_key"]) or columns[0]["name"]
            cursor = source.cursor()
            cursor.execute(f"SELECT {_select_list(columns)} FROM dw.{table} ORDER BY {order}")
            rows = [tuple(row) for row in cursor.fetchall()]
            cursor.close()
            duck.execute(
                f"CREATE TABLE {table} ({', '.join(c['name'] + ' ' + duck_type(c['type']) for c in columns)})"
            )
            duck.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' for _ in columns)})", rows)
            target = (out_dir / f"{table}.parquet").as_posix()
            duck.execute(
                f"COPY (SELECT * FROM {table} ORDER BY {order}) TO '{target}' (FORMAT parquet, COMPRESSION zstd)"
            )
            counts[table] = len(rows)
    finally:
        source.close()
        duck.close()
    return counts


def load_duckdb(sample_dir: Path, database: str = ":memory:") -> Any:
    import duckdb

    con = duckdb.connect(database)
    con.execute("SET TimeZone = 'UTC'")
    con.execute("CREATE SCHEMA IF NOT EXISTS dw")
    for table in SAMPLE_TABLES:
        path = (sample_dir / f"{table}.parquet").as_posix()
        con.execute(f"CREATE OR REPLACE TABLE dw.{table} AS SELECT * FROM read_parquet('{path}')")
    con.execute((sample_dir / "duckdb_views.sql").read_text(encoding="utf-8"))
    return con


def build_sample_gold(
    settings: Settings, questions: list[Question]
) -> tuple[dict[str, GoldEntry], list[str]]:
    """Run every gold query on energiewende_sample (SQL Server, bench_reader). Empty or NULL results are allowed."""
    executor = MssqlExecutor(settings.db, database=settings.db.sample_name)
    entries: dict[str, GoldEntry] = {}
    errors: list[str] = []
    try:
        for q in questions:
            if q.expect != "rows" or not q.gold_sql:
                continue
            result = executor.run(q.gold_sql)
            if not result.ok or result.result is None:
                errors.append(f"{q.id}: {result.error}")
                continue
            entries[q.id] = GoldEntry(
                q.id, "rows", ResultSet.from_json(result.result.to_json()), sql_sha256(q.gold_sql), "sample"
            )
    finally:
        executor.close()
    return entries, errors


def run_parity(
    con: Any, questions: list[Question], sample_gold: dict[str, GoldEntry], compare_settings: CompareSettings
) -> list[ParityRow]:
    executor = DuckDbExecutor(con)
    rows: list[ParityRow] = []
    for q in questions:
        if q.expect != "rows" or not q.gold_sql:
            continue
        if not q.duckdb_ok:
            rows.append(ParityRow(q.id, "skip", q.duckdb.removeprefix("skip: "), False))
            continue
        gold = sample_gold.get(q.id)
        if gold is None or gold.result is None or gold.sql_sha256 != sql_sha256(q.gold_sql):
            rows.append(
                ParityRow(q.id, "missing", "Stichproben-Gold fehlt oder ist veraltet: esb sample gold", False)
            )
            continue
        nontrivial = is_nontrivial(gold.result)
        result = executor.run(q.gold_sql)
        if not result.ok or result.result is None:
            rows.append(ParityRow(q.id, "error", (result.error or "")[:200], nontrivial))
            continue
        rel, abs_ = tolerance_for(q, compare_settings)
        verdict = compare(gold.result, result.result, q.ordered, rel, abs_)
        status = "match" if verdict.match and verdict.strict else "mismatch"
        rows.append(ParityRow(q.id, status, verdict.reason, nontrivial))
    return rows


def parity_summary(rows: list[ParityRow]) -> dict[str, Any]:
    total = len(rows)
    matched = sum(r.status == "match" for r in rows)
    return {
        "coverage": round(matched / total, 6) if total else 0.0,
        "errors": sum(r.status == "error" for r in rows),
        "intents": total,
        "matched": matched,
        "matched_nontrivial": sum(r.status == "match" and r.nontrivial for r in rows),
        "mismatched": sum(r.status == "mismatch" for r in rows),
        "missing": sum(r.status == "missing" for r in rows),
        "rows": [asdict(r) for r in rows],
        "skipped": sum(r.status == "skip" for r in rows),
    }


def render_parity(summary: dict[str, Any]) -> str:
    lines = [
        "# Parität der DuckDB-Stichprobe / DuckDB sample parity",
        "",
        "Erzeugt von `esb sample parity`. Das Gold-SQL (T-SQL) läuft per sqlglot nach DuckDB übersetzt auf der",
        "Stichprobe und muss dieselben Zeilen liefern wie dasselbe Gold-SQL auf `energiewende_sample` in SQL Server.",
        "Generated by `esb sample parity`: gold SQL transpiled to DuckDB must return the rows SQL Server returned",
        "on the identical sample. Details: `docs/dialect-gap.md`.",
        "",
        "| Kennzahl / metric | Wert / value |",
        "|---|---|",
        f"| Intents mit Ergebnis / intents with rows | {summary['intents']} |",
        f"| übereinstimmend / matching | {summary['matched']} ({summary['coverage'] * 100:.1f} %) |",
        f"| davon nicht trivial (Wert ungleich NULL und 0) / of which non-trivial (not NULL, not 0) | {summary['matched_nontrivial']} |",
        f"| davon trivial (leer, nur NULL oder nur 0) / of which trivial (empty, NULL-only or zero-only) | {summary['matched'] - summary['matched_nontrivial']} |",
        f"| abweichend / mismatching | {summary['mismatched']} |",
        f"| Fehler / errors | {summary['errors']} |",
        f"| übersprungen / skipped (`duckdb: skip`) | {summary['skipped']} |",
        f"| Gold fehlt / gold missing | {summary['missing']} |",
        "",
        "| Intent | Status | Grund / reason |",
        "|---|---|---|",
    ]
    lines += [f"| {r['id']} | {r['status']} | {r['reason'].replace('|', '/')} |" for r in summary["rows"]]
    return "\n".join(lines) + "\n"


def content_digests(sample_dir: Path) -> dict[str, dict[str, Any]]:
    """Per table: row count and a SHA-256 over the rows in a fixed order (DuckDB ORDER BY ALL), each cell encoded
    like a gold result (decimals as text, dates as ISO). Independent of Parquet file bytes and compression."""
    import duckdb

    con = duckdb.connect()
    try:
        digests: dict[str, dict[str, Any]] = {}
        for table in SAMPLE_TABLES:
            path = (sample_dir / f"{table}.parquet").as_posix().replace("'", "''")
            cursor = con.execute(f"SELECT * FROM read_parquet('{path}') ORDER BY ALL")
            columns = [d[0] for d in cursor.description]
            sha = hashlib.sha256(json.dumps(columns).encode("utf-8"))
            count = 0
            while batch := cursor.fetchmany(5000):
                for row in batch:
                    line = json.dumps(
                        [encode_value(v) for v in row], ensure_ascii=False, separators=(",", ":")
                    )
                    sha.update(line.encode("utf-8") + b"\n")
                    count += 1
            digests[table] = {"rows": count, "sha256": sha.hexdigest()}
        return digests
    finally:
        con.close()
