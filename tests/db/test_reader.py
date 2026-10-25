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


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM dw.dim_region WHERE region_key = -1",
        "CREATE TABLE dw.esb_probe (a int)",
        "SELECT TOP 1 * FROM stg.smard_series",
        "EXEC xp_cmdshell 'dir'",
    ],
)
def test_permissions_are_denied_without_guard(reader: MssqlExecutor, sql: str) -> None:
    result = reader.run(sql)
    assert result.ok is False
    assert "permission" in (result.error or "").lower()


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
