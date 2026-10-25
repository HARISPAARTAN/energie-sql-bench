import duckdb
import pytest

from energie_sql_bench.execute import transpile_tsql_to_duckdb


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect()
    c.execute("SET TimeZone = 'UTC'")
    c.execute("CREATE SCHEMA dw")
    c.execute(
        "CREATE TABLE dw.t AS SELECT 1 AS a, TIMESTAMP '2025-10-26 00:30:00' AS ts, DATE '2025-01-20' AS d, "
        "true AS b, 'abcd' AS s"
    )
    return c


@pytest.mark.parametrize(
    ("tsql", "fragment", "value"),
    [
        ("SELECT TOP 3 a FROM dw.t ORDER BY a DESC", "LIMIT 3", 1),
        ("SELECT DATETRUNC(hour, ts) AS h FROM dw.t", "DATE_TRUNC('HOUR', ts)", None),
        ("SELECT ISNULL(a, 0) AS a FROM dw.t", "COALESCE(a, 0)", 1),
        ("SELECT DATEDIFF(day, '2024-12-30', d) AS x FROM dw.t", "DATE_DIFF('DAY'", 21),
        ("SELECT DATEPART(hour, ts) AS h FROM dw.t", "EXTRACT(hour FROM ts)", 0),
        ("SELECT CAST(b AS int) AS i FROM dw.t", "CAST(b AS INT)", 1),
        ("SELECT RIGHT(s, 2) AS r FROM dw.t", "RIGHT(", "cd"),
        ("SELECT N'DE-LU' AS r", "'DE-LU'", "DE-LU"),
    ],
)
def test_transpile_cases(con: duckdb.DuckDBPyConnection, tsql: str, fragment: str, value: object) -> None:
    out = transpile_tsql_to_duckdb(tsql)
    assert fragment in out
    result = con.execute(out).fetchone()[0]
    if value is not None:
        assert result == value


def test_windows_zone_name_and_dst(con: duckdb.DuckDBPyConnection) -> None:
    out = transpile_tsql_to_duckdb(
        "SELECT CAST(ts AT TIME ZONE 'UTC' AT TIME ZONE 'W. Europe Standard Time' AS datetime2(0)) AS l FROM dw.t"
    )
    assert "'Europe/Berlin'" in out
    assert str(con.execute(out).fetchone()[0]) == "2025-10-26 02:30:00"


def test_known_gap_integer_division(con: duckdb.DuckDBPyConnection) -> None:
    # SQL Server returns 3 (integer division); DuckDB returns 3.5. Gold SQL avoids int / int (docs/dialect-gap.md).
    assert con.execute(transpile_tsql_to_duckdb("SELECT 7 / 2 AS q")).fetchone()[0] == 3.5


def test_known_gap_dateadd_returns_timestamp(con: duckdb.DuckDBPyConnection) -> None:
    out = transpile_tsql_to_duckdb("SELECT DATEADD(day, -6, d) AS x FROM dw.t")
    assert str(con.execute(out).fetchone()[0]) == "2025-01-14 00:00:00"
