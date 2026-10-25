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
    "SELECT COUNT(*) FROM dw.fact_preis p WHERE EXISTS "
    "(SELECT 1 FROM dw.dim_region r WHERE r.region_key = p.region_key AND r.smard_code = 'DE-LU')",
]


def test_case_counts() -> None:
    assert len(MALICIOUS) == 45
    assert len(BENIGN) == 30


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
