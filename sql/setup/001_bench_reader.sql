-- Least-privilege login for Energie-SQL-Bench, run by tools/setup_reader.py as sa (idempotent).
-- Batch 1 runs in master; its single ODBC parameter is the reader password from the git-ignored .env.
DECLARE @pw nvarchar(128) = ?;
DECLARE @sql nvarchar(max);
IF SUSER_ID(N'bench_reader') IS NULL
    SET @sql = N'CREATE LOGIN bench_reader WITH PASSWORD = ' + QUOTENAME(@pw, '''')
             + N', DEFAULT_DATABASE = energiewende, CHECK_POLICY = ON, CHECK_EXPIRATION = OFF';
ELSE
    SET @sql = N'ALTER LOGIN bench_reader WITH PASSWORD = ' + QUOTENAME(@pw, '''')
             + N', DEFAULT_DATABASE = energiewende';
EXEC sys.sp_executesql @sql;
GO
-- Batch 2 runs in each benchmark database (energiewende; later energiewende_sample).
IF DATABASE_PRINCIPAL_ID(N'bench_reader') IS NULL
    CREATE USER bench_reader FOR LOGIN bench_reader;
GRANT SELECT ON SCHEMA::dw TO bench_reader;
GRANT SELECT ON SCHEMA::rpt TO bench_reader;
GRANT VIEW DEFINITION ON SCHEMA::dw TO bench_reader;
GRANT VIEW DEFINITION ON SCHEMA::rpt TO bench_reader;
IF SCHEMA_ID(N'stg') IS NOT NULL
    DENY SELECT ON SCHEMA::stg TO bench_reader;
