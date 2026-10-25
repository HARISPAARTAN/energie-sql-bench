"""Read-only executors: SQL Server through pyodbc as bench_reader, and DuckDB for the CI sample.

pyodbc is imported lazily so that CI, which never talks to SQL Server, does not need the ODBC driver.
"""

from __future__ import annotations

import datetime as dt
import re
import struct
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from energie_sql_bench.config import DbSettings, odbc_quote
from energie_sql_bench.resultset import ResultSet, infer_types

WINDOWS_ZONES = {"'W. Europe Standard Time'": "'Europe/Berlin'"}
_ODBC_PREFIX = re.compile(r"\[[^\]]*\]")


@dataclass(frozen=True)
class ExecResult:
    ok: bool
    result: ResultSet | None
    error: str | None
    error_kind: str | None  # "timeout" | "db_error" | "no_result" | None
    db_ms: float

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "result": self.result.to_json() if self.result is not None else None,
            "error": self.error,
            "error_kind": self.error_kind,
            "db_ms": self.db_ms,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ExecResult:
        result = ResultSet.from_json(data["result"]) if data.get("result") is not None else None
        return cls(bool(data["ok"]), result, data.get("error"), data.get("error_kind"), float(data["db_ms"]))


class Executor(Protocol):
    def run(self, sql: str) -> ExecResult: ...

    def close(self) -> None: ...


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 3)


def split_batches(script: str) -> list[str]:
    """Split a T-SQL script on lines that contain only GO (case-insensitive)."""
    parts: list[str] = []
    current: list[str] = []
    for line in script.splitlines():
        if line.strip().upper() == "GO":
            parts.append("\n".join(current).strip())
            current = []
        else:
            current.append(line)
    parts.append("\n".join(current).strip())
    return [p for p in parts if p]


def fetch_all(con: Any, sql: str, params: tuple = ()) -> list[tuple]:
    cursor = con.cursor()
    if params:
        cursor.execute(sql, *params)
    else:
        cursor.execute(sql)
    rows = [tuple(row) for row in cursor.fetchall()]
    cursor.close()
    return rows


SQL_SS_TIMESTAMPOFFSET = -155  # datetimeoffset: pyodbc has no built-in mapping


def datetimeoffset_from_bytes(raw: bytes) -> dt.datetime:
    """Decode the SQL_SS_TIMESTAMPOFFSET_STRUCT of the ODBC driver into an aware datetime (microsecond precision)."""
    year, month, day, hour, minute, second, nanoseconds, tz_hour, tz_minute = struct.unpack("<6hI2h", raw)
    offset = dt.timezone(dt.timedelta(hours=tz_hour, minutes=tz_minute))
    return dt.datetime(year, month, day, hour, minute, second, nanoseconds // 1000, tzinfo=offset)


def connect_mssql(db: DbSettings, database: str | None = None) -> Any:
    """A bench_reader connection: autocommit, query timeout and lock timeout from the settings."""
    import pyodbc

    con = pyodbc.connect(db.connection_string(database), autocommit=True, timeout=10)
    con.timeout = db.query_timeout_s
    con.add_output_converter(SQL_SS_TIMESTAMPOFFSET, datetimeoffset_from_bytes)
    con.execute(f"SET LOCK_TIMEOUT {int(db.lock_timeout_ms)}")
    return con


@contextmanager
def admin_connect(db: DbSettings, sa_password: str, database: str) -> Iterator[Any]:
    """An sa connection for setup scripts only (login creation, sample database). Never used for benchmarking."""
    import pyodbc

    cs = (
        f"DRIVER={{{db.driver}}};SERVER={db.server};DATABASE={database};UID=sa;PWD={odbc_quote(sa_password)};"
        "Encrypt=yes;TrustServerCertificate=yes"
    )
    with closing(pyodbc.connect(cs, autocommit=True, timeout=10)) as con:
        yield con


def _rows_result(cursor: Any, max_rows: int) -> ResultSet:
    columns = [str(d[0]) for d in cursor.description]
    fetched = cursor.fetchmany(max_rows + 1)
    truncated = len(fetched) > max_rows
    rows = [list(row) for row in fetched[:max_rows]]
    return ResultSet(columns, infer_types(rows, len(columns)), rows, truncated)


def _clean_mssql_error(exc: Exception) -> tuple[str, str]:
    """(sqlstate, message) without the ODBC driver prefixes and the API call suffix."""
    sqlstate = str(exc.args[0]) if exc.args else ""
    text = str(exc.args[1]) if len(exc.args) > 1 else str(exc)
    text = _ODBC_PREFIX.sub("", text).replace("(SQLExecDirectW)", "").strip()
    return sqlstate, f"{sqlstate}: {text}"


class MssqlExecutor:
    def __init__(self, db: DbSettings, database: str | None = None, max_rows: int | None = None) -> None:
        self._db = db
        self._database = database
        self._max_rows = max_rows or db.max_rows
        self._con: Any = None

    def _connection(self) -> Any:
        if self._con is None:
            self._con = connect_mssql(self._db, self._database)
        return self._con

    def run(self, sql: str) -> ExecResult:
        import pyodbc

        start = time.perf_counter()
        try:
            cursor = self._connection().cursor()
            cursor.execute(sql)
            if cursor.description is None:
                cursor.close()
                return ExecResult(
                    False, None, "Die Anweisung liefert keine Ergebnismenge", "no_result", _ms(start)
                )
            result = _rows_result(cursor, self._max_rows)
            cursor.close()
            return ExecResult(True, result, None, None, _ms(start))
        except pyodbc.Error as exc:
            sqlstate, message = _clean_mssql_error(exc)
            kind = "timeout" if sqlstate == "HYT00" or "timeout expired" in message.lower() else "db_error"
            return ExecResult(False, None, message, kind, _ms(start))

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None


def transpile_tsql_to_duckdb(sql: str) -> str:
    import sqlglot

    out = sqlglot.transpile(sql, read="tsql", write="duckdb")
    if len(out) != 1:
        raise ValueError("genau eine Anweisung erwartet")
    text = out[0]
    for windows_name, iana_name in WINDOWS_ZONES.items():
        text = text.replace(windows_name, iana_name)
    return text


class DuckDbExecutor:
    def __init__(self, con: Any, max_rows: int = 10000, transpile: bool = True) -> None:
        self._con = con
        self._max_rows = max_rows
        self._transpile = transpile

    def run(self, sql: str) -> ExecResult:
        import duckdb
        from sqlglot.errors import SqlglotError

        start = time.perf_counter()
        try:
            target = transpile_tsql_to_duckdb(sql) if self._transpile else sql
        except (SqlglotError, ValueError) as exc:
            return ExecResult(False, None, f"transpile: {str(exc).splitlines()[0]}", "db_error", _ms(start))
        try:
            cursor = self._con.execute(target)
            if cursor.description is None:
                return ExecResult(
                    False, None, "Die Anweisung liefert keine Ergebnismenge", "no_result", _ms(start)
                )
            result = _rows_result(cursor, self._max_rows)
            return ExecResult(True, result, None, None, _ms(start))
        except duckdb.Error as exc:
            return ExecResult(False, None, str(exc).splitlines()[0], "db_error", _ms(start))

    def close(self) -> None:
        self._con.close()
