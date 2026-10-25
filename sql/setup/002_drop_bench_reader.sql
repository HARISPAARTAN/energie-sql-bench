-- Removes the benchmark login, run by tools/setup_reader.py --drop as sa.
-- Batch 1 runs in each benchmark database, batch 2 in master.
IF DATABASE_PRINCIPAL_ID(N'bench_reader') IS NOT NULL
    DROP USER bench_reader;
GO
IF SUSER_ID(N'bench_reader') IS NOT NULL
    DROP LOGIN bench_reader;
