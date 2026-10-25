import duckdb

from energie_sql_bench.execute import DuckDbExecutor, ExecResult, split_batches, transpile_tsql_to_duckdb
from energie_sql_bench.resultset import ResultSet


def make_con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE SCHEMA dw")
    con.execute("CREATE TABLE dw.t (x INTEGER, d DECIMAL(9,2))")
    con.execute("INSERT INTO dw.t VALUES (1, 1.50), (2, 2.25), (3, -0.75)")
    return con


def test_top_is_transpiled_to_limit() -> None:
    result = DuckDbExecutor(make_con()).run("SELECT TOP 2 x FROM dw.t ORDER BY x DESC")
    assert result.ok, result.error
    assert result.result.rows == [[3], [2]]


def test_row_cap_flags_truncation() -> None:
    result = DuckDbExecutor(make_con(), max_rows=2).run("SELECT x FROM dw.t ORDER BY x")
    assert result.ok
    assert result.result.truncated is True
    assert len(result.result.rows) == 2


def test_database_error_is_reported() -> None:
    result = DuckDbExecutor(make_con()).run("SELECT nope FROM dw.t")
    assert result.ok is False
    assert result.error_kind == "db_error"
    assert result.error


def test_windows_zone_is_mapped() -> None:
    sql = (
        "SELECT CAST(ts AT TIME ZONE 'UTC' AT TIME ZONE 'W. Europe Standard Time' AS datetime2(0)) FROM dw.t"
    )
    assert "Europe/Berlin" in transpile_tsql_to_duckdb(sql)


def test_split_batches() -> None:
    assert split_batches("A\nGO\nB\n go \nC") == ["A", "B", "C"]


def test_types_and_json_roundtrip() -> None:
    result = DuckDbExecutor(make_con()).run("SELECT d FROM dw.t ORDER BY x")
    assert result.result.types == ["decimal"]
    assert ResultSet.from_json(result.result.to_json()) == result.result
    assert ExecResult.from_json(result.to_json()) == result
