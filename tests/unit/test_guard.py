import pytest

from energie_sql_bench.guard import check_sql

MALICIOUS = [
    "DELETE FROM dw.fact_preis",
    "UPDATE dw.fact_preis SET day_ahead_eur_mwh = 0",
    "INSERT INTO dw.dim_region (region_key, smard_code) VALUES (9, N'X')",
    "DROP TABLE dw.fact_preis",
    "TRUNCATE TABLE dw.fact_last",
    "CREATE TABLE dw.esb_probe (a int)",
    "ALTER TABLE dw.fact_preis ADD x int",
    "MERGE dw.dim_region AS t USING dw.dim_region AS s ON t.region_key = s.region_key WHEN MATCHED THEN DELETE;",
    "SELECT * INTO dw.kopie FROM dw.fact_preis",
    "SELECT * INTO #tmp FROM dw.fact_preis",
    "EXEC xp_cmdshell 'dir'",
    "EXECUTE sp_who",
    "EXEC('SELECT 1')",
    "DECLARE @x int = 1; SELECT @x",
    "SET NOCOUNT ON",
    "USE master",
    "WAITFOR DELAY '00:00:10'",
    "SELECT 1; WAITFOR DELAY '00:00:10'",
    "SELECT * FROM dw.fact_preis; DROP TABLE dw.fact_preis",
    "SELECT * FROM OPENROWSET('SQLNCLI', 'Server=x;Trusted_Connection=yes;', 'SELECT 1')",
    "SELECT * FROM OPENQUERY(fremd, 'SELECT 1')",
    "SELECT * FROM OPENDATASOURCE('SQLNCLI', 'Data Source=x').db.dbo.t",
    "SELECT name FROM sys.objects",
    "SELECT * FROM sys.sql_logins",
    "SELECT * FROM INFORMATION_SCHEMA.TABLES",
    "SELECT * FROM stg.smard_series",
    "SELECT * FROM dbo.irgendwas",
    "SELECT * FROM master.dbo.sysdatabases",
    "SELECT * FROM energiewende.stg.smard_series",
    "SELECT * FROM fremdserver.energiewende.dw.fact_preis",
    "SELECT * FROM fact_preis",
    "SELECT * FROM dw.fact_preis WHERE 1 = (SELECT COUNT(*) FROM sys.tables)",
    "WITH x AS (SELECT * FROM stg.smard_series) SELECT * FROM x",
    "SELECT region_key FROM dw.fact_preis UNION ALL SELECT filter_id FROM stg.smard_series",
    "SELECT * FROM dw.fact_preis WHERE xp_cmdshell('dir') = 1",
    "SELECT @@VERSION",
    "SELECT SUSER_SNAME()",
    "SELECT * FROM dw.fact_preis /* harmlos */; DELETE FROM dw.fact_preis",
    "SELECT 1 -- Kommentar\n; DROP TABLE dw.x",
    "GRANT SELECT ON SCHEMA::stg TO public",
    "BEGIN TRANSACTION",
    "SHUTDOWN",
    "DBCC CHECKDB",
    "BACKUP DATABASE energiewende TO DISK = 'C:\\temp\\x.bak'",
    "",
    # Review findings on Task 2: the catalog and CTE-shadow checks, each the only layer that stops its case.
    "SELECT * FROM energiewende_sample.dw.fact_preis",
    "SELECT * FROM otherdb.dw.t",
    "WITH a AS (SELECT 1 x) SELECT * FROM stg.a",
    # Statement keywords that sqlglot reads as aliases but SQL Server runs as a second statement.
    "SELECT 1 COMMIT",
    "SELECT * FROM dw.fact_preis COMMIT",
    "SELECT 1 AS a CHECKPOINT",
    "SELECT * FROM dw.fact_preis p RETURN",
    "SELECT 1 a BREAK",
    "SELECT 1 a CONTINUE",
    "SELECT 1 a THROW",
    "SELECT 1 a ROLLBACK",
    "SELECT 1 a PRINT",
    "SELECT 1 a RAISERROR",
    "SELECT 1 a GOTO x",
    "SELECT 1 a WHILE",
    "SELECT 1 a IF",
    # Reserved words as unquoted aliases.
    "SELECT 1 user",
    "SELECT 1 AS percent",
    "SELECT * FROM dw.fact_preis AS table",
    # Sequences, lock hints, query hints, FOR clauses.
    "SELECT NEXT VALUE FOR dw.seq",
    "SELECT * FROM dw.fact_preis WITH (TABLOCKX)",
    "SELECT * FROM dw.fact_preis WITH (UPDLOCK)",
    "SELECT * FROM dw.fact_preis WITH (NOLOCK, XLOCK)",
    "SELECT * FROM dw.fact_preis WITH (HOLDLOCK)",
    "SELECT * FROM dw.fact_preis (TABLOCK)",
    "SELECT * FROM dw.fact_preis OPTION (MAXDOP 1)",
    "SELECT * FROM dw.fact_preis FOR XML AUTO",
    # System objects, function-valued table sources, APPLY, user-defined and unlisted functions.
    "SELECT * FROM dw.fact_preis CROSS APPLY sys.dm_exec_sql_text(0x) x",
    "SELECT * FROM dw.fact_preis CROSS APPLY OPENJSON(a) x",
    "SELECT * FROM dw.fact_preis OUTER APPLY dbo.fn_x(1) x",
    "SELECT * FROM STRING_SPLIT('a,b', ',')",
    "SELECT * FROM GENERATE_SERIES(1, 10)",
    "SELECT sys.fn_x(1)",
    "SELECT dbo.fn_x(1)",
    "SELECT dw.fn_x(1)",
    "SELECT dw.str(1)",
    "SELECT dbo.some_column FROM dw.fact_preis",
    "SELECT * FROM GETUTCDATE()",
    "SELECT * FROM dw.str(1)",
    "SELECT * FROM dw.fact_preis CROSS APPLY ABS(1) x",
    "SELECT OBJECT_NAME(1)",
    "SELECT ORIGINAL_LOGIN()",
    "SELECT APP_NAME()",
    "SELECT DB_NAME()",
    "SELECT NEWID()",
    "SELECT * FROM dw.fact_preis WHERE a = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES)",
    "SELECT * FROM dw.fact_preis WHERE a = (SELECT COUNT(*) FROM sys.tables)",
    # Review R1: OPTION on a set-operation root lifts MAXRECURSION and other query limits.
    "SELECT 1 AS a UNION ALL SELECT 2 OPTION (MAXRECURSION 0)",
    "SELECT 1 AS a EXCEPT SELECT 2 OPTION (MAXRECURSION 0)",
    "SELECT 1 AS a INTERSECT SELECT 2 OPTION (RECOMPILE)",
    "WITH x AS (SELECT 1 a UNION ALL SELECT a + 1 FROM x) SELECT a FROM x UNION ALL SELECT 1 OPTION (MAXRECURSION 0)",
    "SELECT * FROM (SELECT 1 AS a UNION SELECT 2 OPTION (HASH JOIN)) AS t",
    # Review R1: statement words that a bare SELECT 1 <word> lets through unless the word list stops them.
    "SELECT 1 DISABLE",
    "SELECT 1 ENABLE",
    "SELECT 1 GET",
    "SELECT 1 GO",
    "SELECT 1 MOVE",
    "SELECT 1 RECEIVE",
    "SELECT 1 SEND",
    "SELECT 1 THROW",
    # Review I1: a CTE name defined later in the same WITH list is an ordinary table reference inside an
    # earlier CTE and reaches the legacy catalog views; and the legacy views by their bare name.
    "WITH a AS (SELECT name FROM sysobjects), sysobjects AS (SELECT N'x' AS name) SELECT TOP 3 name FROM a",
    "WITH a AS (SELECT name FROM syslogins), syslogins AS (SELECT N'x' AS name) SELECT name FROM a",
    "WITH a AS (SELECT name FROM sysusers), sysusers AS (SELECT N'x' AS name) SELECT name FROM a",
    "WITH a AS (SELECT name FROM sysdatabases), sysdatabases AS (SELECT N'x' AS name) SELECT name FROM a",
    "WITH a AS (SELECT 1 x FROM b), b AS (SELECT 1 x) SELECT x FROM a",
    "WITH sysobjects AS (SELECT name FROM sysobjects) SELECT name FROM sysobjects",
    "SELECT name FROM sysobjects",
    "SELECT name FROM syscolumns",
    "SELECT name FROM [sysindexes]",
]

BENIGN = [
    "SELECT AVG(day_ahead_eur_mwh) FROM dw.fact_preis",
    "SELECT TOP 5 name_de FROM dw.dim_bundesland ORDER BY name_de",
    "SELECT e.name_de, SUM(f.erzeugung_mwh) AS mwh FROM dw.fact_erzeugung f "
    "JOIN dw.dim_energietraeger e ON e.energietraeger_key = f.energietraeger_key GROUP BY e.name_de",
    "WITH x AS (SELECT datum_key, day_ahead_eur_mwh FROM dw.fact_preis) SELECT COUNT(*) FROM x WHERE day_ahead_eur_mwh < 0",
    "SELECT * FROM rpt.v_negative_preisphasen",
    "SELECT datum_key, AVG(day_ahead_eur_mwh) OVER (ORDER BY datum_key ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS g "
    "FROM dw.fact_preis",
    "SELECT 1 AS a UNION ALL SELECT 2",
    "SELECT name_de FROM dw.dim_region INTERSECT SELECT name_de FROM rpt.v_dim_region",
    "SELECT name_de FROM dw.dim_region EXCEPT SELECT name_de FROM rpt.v_dim_region",
    "SELECT * FROM (SELECT TOP 10 * FROM dw.fact_preis ORDER BY ts_utc) AS t",
    "SELECT [name_de] FROM [dw].[dim_bundesland] WHERE [kuerzel] = 'BY'",
    "-- alles loeschen? nein\nSELECT COUNT(*) FROM dw.fact_last",
    "/* DROP TABLE dw.x */ SELECT 1 AS eins",
    "SELECT N'DELETE FROM dw.fact_preis; EXEC xp_cmdshell' AS text",
    "SELECT COUNT(*) FROM dw.fact_preis;",
    "SELECT CAST(ts_utc AT TIME ZONE 'UTC' AT TIME ZONE 'W. Europe Standard Time' AS datetime2(0)) AS lokal FROM dw.fact_preis",
    "SELECT DATEADD(hour, 1, ts_utc) AS a, DATEDIFF(day, '2024-01-01', ts_utc) AS b FROM dw.fact_preis",
    "SELECT ISNULL(netzlast_mwh, 0) AS n FROM dw.fact_last",
    "SELECT CASE WHEN day_ahead_eur_mwh < 0 THEN 1 ELSE 0 END AS negativ FROM dw.fact_preis",
    "SELECT d.jahr, COUNT(*) AS n FROM dw.fact_preis p JOIN dw.dim_datum d ON d.datum_key = p.datum_key "
    "GROUP BY d.jahr HAVING COUNT(*) > 100",
    "SELECT ROW_NUMBER() OVER (PARTITION BY d.jahr ORDER BY p.day_ahead_eur_mwh DESC) AS rn FROM dw.fact_preis p "
    "JOIN dw.dim_datum d ON d.datum_key = p.datum_key",
    "SELECT LAG(netzlast_mwh) OVER (ORDER BY ts_utc) AS vorher FROM dw.fact_last",
    "SELECT * FROM dw.fact_preis WITH (NOLOCK)",
    "SELECT * FROM dw.fact_preis ORDER BY ts_utc OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY",
    "SELECT DISTINCT kategorie_de FROM dw.dim_energietraeger",
    "SELECT TOP (3) datum_key FROM dw.fact_preis ORDER BY day_ahead_eur_mwh DESC",
    "SELECT DATETRUNC(month, ts_utc) AS monat, SUM(netzlast_mwh) AS mwh FROM dw.fact_last GROUP BY DATETRUNC(month, ts_utc)",
    "SELECT k.bestand_mw FROM dw.fact_kapazitaet AS k WHERE k.datum_key = 20260901",
    "SELECT b.name_de FROM dw.dim_bundesland b WHERE b.name_de LIKE N'%Sachsen%'",
    "SELECT * FROM dw.fact_preis AS p WITH (READUNCOMMITTED)",
    "SELECT * FROM dw.fact_preis (NOLOCK)",
    "SELECT p.region_key, x.m FROM dw.fact_preis p CROSS APPLY (SELECT MAX(day_ahead_eur_mwh) AS m FROM dw.fact_preis) x",
    "SELECT 1 AS [percent], CHOOSE(2, 'a', 'b') AS c, STDEV(day_ahead_eur_mwh) AS s FROM dw.fact_preis",
    "SELECT * FROM dw.fact_preis WHERE tag = 'COMMIT' OR tag = 'GO' OR tag = N'sys.objects'",
    "SELECT COUNT(*) FROM dw.fact_preis p WHERE EXISTS "
    "(SELECT 1 FROM dw.dim_region r WHERE r.region_key = p.region_key AND r.smard_code = 'DE-LU')",
    # Correctly ordered CTE chains, and a recursive CTE that refers to itself.
    "WITH a AS (SELECT datum_key FROM dw.fact_preis), b AS (SELECT datum_key FROM a) SELECT COUNT(*) FROM b",
    "WITH a AS (SELECT 1 AS n), b AS (SELECT n FROM a), c AS (SELECT n FROM a JOIN b ON b.n = a.n) "
    "SELECT n FROM c",
    "WITH r AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM r WHERE n < 5) SELECT n FROM r",
    "WITH a AS (SELECT 1 AS n) SELECT n FROM a UNION ALL SELECT n FROM a",
]


def test_case_counts() -> None:
    assert len(MALICIOUS) == 45 + 3 + 13 + 3 + 8 + 20 + 5 + 8 + 9 == 114
    assert len(BENIGN) == 30 + 5 + 4


@pytest.mark.parametrize("sql", MALICIOUS)
def test_malicious_is_blocked(sql: str) -> None:
    assert check_sql(sql).allowed is False


@pytest.mark.parametrize("sql", BENIGN)
def test_benign_is_allowed(sql: str) -> None:
    result = check_sql(sql)
    assert result.allowed, result.reason


def test_tables_are_reported_sorted() -> None:
    result = check_sql("SELECT * FROM dw.fact_preis p JOIN rpt.v_dim_region r ON r.region_key = p.region_key")
    assert result.tables == ("dw.fact_preis", "rpt.v_dim_region")


def test_cte_name_is_not_a_table() -> None:
    result = check_sql("WITH x AS (SELECT 1 AS a) SELECT a FROM x")
    assert result.allowed and result.tables == ()


def test_parse_error_is_flagged() -> None:
    result = check_sql("SELECT (1")
    assert result.allowed is False and result.parse_error is True


def test_missing_schema_reason() -> None:
    assert "ohne Schema" in check_sql("SELECT * FROM fact_preis").reason


def test_none_is_blocked() -> None:
    assert check_sql(None).allowed is False


def nested(open_: str, inner: str, close: str, depth: int) -> str:
    return open_ * depth + inner + close * depth


def test_deep_parentheses_are_blocked_not_raised() -> None:
    result = check_sql("SELECT " + nested("(", "1", ")", 500))
    assert result.allowed is False and result.parse_error is True


def test_deep_subqueries_are_blocked_not_raised() -> None:
    result = check_sql("SELECT * FROM " + nested("(SELECT * FROM ", "dw.fact_preis", ") AS s", 300))
    assert result.allowed is False and result.parse_error is True


def test_deep_case_is_blocked_not_raised() -> None:
    result = check_sql("SELECT " + nested("CASE WHEN 1 = 1 THEN ", "1", " END", 1000))
    assert result.allowed is False and result.parse_error is True


def test_nesting_beyond_the_cap_is_blocked_before_the_parser_runs() -> None:
    # 60 levels parse fine, so only the explicit cap stops them (not the RecursionError fallback).
    for sql in (
        "SELECT " + nested("(", "1", ")", 60),
        "SELECT " + nested("CASE WHEN 1 = 1 THEN ", "1", " END", 60),
    ):
        result = check_sql(sql)
        assert result.allowed is False and "verschachtelt" in result.reason


def test_moderate_nesting_is_allowed() -> None:
    assert check_sql("SELECT " + nested("(", "1", ")", 30)).allowed


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM dw.fact_preis WHERE " + "NOT " * 5000 + "1 = 1",
        "SELECT " + "(" * 100_000,
        "SELECT " + ")" * 500,
        chr(0),
        "SELECT '",
    ],
    ids=["not-chain", "unclosed-parens", "closing-parens", "nul-byte", "open-string"],
)
def test_check_sql_never_raises(sql: str) -> None:
    result = check_sql(sql)
    assert result.allowed is False


def test_forward_reference_reason_names_the_legacy_view() -> None:
    result = check_sql(
        "WITH a AS (SELECT name FROM syslogins), syslogins AS (SELECT N'x' AS name) SELECT name FROM a"
    )
    assert "Systemsicht" in result.reason


def test_cte_reference_to_a_later_cte_is_a_plain_table() -> None:
    result = check_sql("WITH a AS (SELECT 1 x FROM b), b AS (SELECT 1 x) SELECT x FROM a")
    assert result.allowed is False and "ohne Schema" in result.reason


def test_main_query_sees_every_cte_and_later_ctes_see_earlier_ones() -> None:
    sql = "WITH a AS (SELECT 1 AS n), b AS (SELECT n FROM a) SELECT n FROM a UNION ALL SELECT n FROM b"
    assert check_sql(sql).allowed
