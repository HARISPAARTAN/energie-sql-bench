import datetime as dt

import pytest

from energie_sql_bench.config import Settings
from energie_sql_bench.execute import MssqlExecutor

pytestmark = pytest.mark.db


def test_select_on_dw_works(reader: MssqlExecutor) -> None:
    result = reader.run("SELECT COUNT(*) AS n FROM dw.dim_region")
    assert result.ok, result.error
    assert result.result.rows == [[5]]


def test_default_database(reader: MssqlExecutor) -> None:
    assert reader.run("SELECT DB_NAME() AS db").result.rows == [["energiewende"]]


# (statement, SQL Server error number). The data-changing forms select no rows (WHERE 1 = 0), so nothing
# would persist if a grant ever regressed; CREATE TABLE is the one exception and is checked by number too.
DENIED = [
    ("INSERT INTO dw.dim_region (region_key, smard_code) SELECT 9, N'X' WHERE 1 = 0", 229),
    ("UPDATE dw.dim_region SET smard_code = N'X' WHERE 1 = 0", 229),
    ("DELETE FROM dw.dim_region WHERE 1 = 0", 229),
    ("DELETE FROM dw.dim_region WHERE region_key = -1", 229),
    ("CREATE TABLE dw.esb_probe (a int)", 262),
    ("SELECT TOP 1 * FROM stg.smard_series", 229),
    ("SELECT TOP 1 * FROM energiewende.stg.smard_series", 229),
    ("SELECT TOP 1 * FROM msdb.dbo.sysjobs", 229),
    ("EXEC xp_cmdshell 'dir'", 229),
]


@pytest.mark.parametrize(("sql", "number"), DENIED, ids=[f"{n}-{i}" for i, (_, n) in enumerate(DENIED)])
def test_permissions_are_denied_without_guard(reader: MssqlExecutor, sql: str, number: int) -> None:
    result = reader.run(sql)
    assert result.ok is False
    assert result.error_kind == "db_error"
    assert f"({number})" in (result.error or ""), result.error


def test_lock_timeout_is_set_on_connect(reader: MssqlExecutor, settings: Settings) -> None:
    result = reader.run("SELECT @@LOCK_TIMEOUT AS ms")
    assert result.ok, result.error
    assert result.result.rows == [[settings.db.lock_timeout_ms]]


def test_datetimeoffset_is_returned_as_aware_datetime(reader: MssqlExecutor) -> None:
    sql = (
        "SELECT CAST('2025-10-04T21:00:00' AS datetime2) AT TIME ZONE 'UTC' "
        "AT TIME ZONE 'W. Europe Standard Time' AS lokal"
    )
    result = reader.run(sql)
    assert result.ok, result.error
    value = result.result.rows[0][0]
    assert value == dt.datetime(2025, 10, 4, 23, 0, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    assert result.result.types == ["datetime"]


def test_datetimeoffset_keeps_microseconds_negative_offset_and_null(reader: MssqlExecutor) -> None:
    result = reader.run(
        "SELECT TODATETIMEOFFSET(CAST('2025-01-04T21:00:00.1234567' AS datetime2), '-03:30') AS a, "
        "CAST(NULL AS datetimeoffset) AS b, SYSDATETIMEOFFSET() AS c"
    )
    assert result.ok, result.error
    a, b, c = result.result.rows[0]
    assert a == dt.datetime(
        2025, 1, 4, 21, 0, 0, 123456, tzinfo=dt.timezone(-dt.timedelta(hours=3, minutes=30))
    )
    assert b is None
    assert c.tzinfo is not None


def test_query_timeout(settings: Settings) -> None:
    executor = MssqlExecutor(settings.db.with_overrides(query_timeout_s=2))
    try:
        result = executor.run("WAITFOR DELAY '00:00:05'")
    finally:
        executor.close()
    assert result.ok is False
    assert result.error_kind == "timeout"


def test_row_cap(settings: Settings) -> None:
    executor = MssqlExecutor(settings.db, max_rows=10)
    try:
        result = executor.run("SELECT TOP 20 datum_key FROM dw.dim_datum ORDER BY datum_key")
    finally:
        executor.close()
    assert result.ok and result.result.truncated and len(result.result.rows) == 10
