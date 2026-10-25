# Dialekt-Lücke T-SQL / DuckDB (CI-Stichprobe)

Der Benchmark misst ausschließlich gegen SQL Server 2022. DuckDB dient nur dazu, dass die CI ohne SQL Server
prüfen kann, ob Harness, Vergleich und Gold-Abfragen zusammenpassen: Gold-SQL wird mit sqlglot (`read="tsql"`,
`write="duckdb"`) übersetzt und auf einer Stichprobe ausgeführt, die Zeile für Zeile der SQL-Server-Datenbank
`energiewende_sample` entspricht. Ergebnisse aus DuckDB fließen nie in eine Bewertung ein.

## Stichprobe

| Teil | Inhalt |
|---|---|
| Zeitreihen (`fact_erzeugung`, `fact_last`, `fact_preis`) | ISO-Woche 24/2025 (09.–15.06.2025, die meisten negativen Preisstunden) und ISO-Woche 43/2025 (20.–26.10.2025, Zeitumstellung am 26.10. mit 100 Viertelstunden) |
| Kapazität (`fact_kapazitaet`) | Monate 2026-07, 2026-08, 2026-09 |
| Kalender (`dim_datum`) | 2025 und 2026 |
| übrige Dimensionen | vollständig |

Fragen über 2023, 2024 oder ganze Jahre liefern auf der Stichprobe meist eine einzige NULL-Zeile oder keine
Zeile. Solche Übereinstimmungen zählen in `reports/parity.md` als „trivial“. `rpt.v_dq_luecken` rechnet die
Lücke zwischen den beiden Wochen als fehlend; das ist eine Eigenschaft der Stichprobe, keine Dialektfrage, und
betrifft beide Engines gleich.

## Bekannte Unterschiede

| Konstrukt | SQL Server | DuckDB nach sqlglot | Umgang |
|---|---|---|---|
| `TOP n` | Zeilenbegrenzung | `LIMIT n` | gleichwertig |
| `LIMIT n` im T-SQL | Syntaxfehler | gültig | Der synthetische Fehlertyp 6 (Gold-SQL plus `LIMIT 10`) ist auf DuckDB kein Fehler; der End-to-End-Test lässt diese Items aus. |
| `int / int` | ganzzahlige Division (`7 / 2 = 3`) | Dezimaldivision (`3.5`) | Gold-SQL dividiert nie zwei Ganzzahlen; sonst `duckdb: skip` |
| `AVG(int)` | ganzzahliges Ergebnis | `DOUBLE` | Gold-SQL mittelt nur Dezimalspalten oder castet vorher |
| `DATEADD(day, n, date)` | `date` | `TIMESTAMP` | Vergleich normalisiert Datum und Zeit; in Ergebnisspalten `CAST(... AS date)` verwenden |
| Zeitzonen | `AT TIME ZONE 'W. Europe Standard Time'` | `AT TIME ZONE 'Europe/Berlin'` (Ersetzung in `transpile_tsql_to_duckdb`), Sitzung mit `TimeZone = 'UTC'` | gleichwertig, wenn das Ergebnis mit `CAST(... AS datetime2)` wieder lokal und ohne Offset ist; ein `datetimeoffset` bzw. `TIMESTAMPTZ` in der Ergebnisspalte wird verschieden dargestellt |
| Zeichenkettenvergleich | Kollation `Latin1_General_CI_AS`: Groß/Klein egal, Leerzeichen am Ende egal | Groß/Klein relevant | Gold-SQL schreibt Namen exakt wie in den Dimensionen; `char(3)`-Kürzel sind in Parquet rechts getrimmt |
| `NULL` in `ORDER BY ... ASC` | zuerst | zuletzt | Gold-SQL mit `ordered: true` sortiert nicht über NULL-fähige Spalten oder setzt die Reihenfolge explizit |
| `SUM`/`AVG` über `decimal` | `decimal(38, s)` | `DECIMAL` oder `DOUBLE` | Toleranz `rel_tol 1e-4`, `abs_tol 0.005` |
| `FORMAT(x, 'yyyy-MM')` | .NET-Format | `STRFTIME` | nur einfache Datumsformate übersetzbar; sonst `duckdb: skip` |
| `CONVERT(typ, x, stil)` mit Stilcode | Stilcodes | nicht übersetzt | in Gold-SQL vermeiden |
| `DATETRUNC`, `ISNULL`, `DATEDIFF`, `DATEPART` | nativ | `DATE_TRUNC`, `COALESCE`, `DATE_DIFF`, `EXTRACT` | gleichwertig (Unit-Tests in `tests/unit/test_dialect.py`) |

## Prüfung

- `esb sample gold` führt das Gold-SQL auf `energiewende_sample` in SQL Server aus (Ergebnis in `data/sample/gold_mssql/`).
- `esb sample parity` führt dasselbe Gold-SQL übersetzt in DuckDB aus und vergleicht mit demselben Vergleicher wie der Benchmark.
- Abnahme: mindestens 80 % der 64 Intents mit Ergebnis (70 Intents minus 6 Abstinenz-Intents) stimmen überein und mindestens 15 davon nicht trivial.
- Übersprungene Intents stehen mit Grund in `reports/parity.md` und im Feld `duckdb` der Frage. Stand der Erzeugung: alle 64 stimmen überein, keiner wurde übersprungen.

---

# Dialect gap T-SQL / DuckDB (CI sample), English summary

The benchmark measures SQL Server 2022 only. DuckDB lets CI check without SQL Server that harness, comparator and
gold queries fit together: gold SQL is transpiled with sqlglot and run on a slice that matches the SQL Server
database `energiewende_sample` row for row. DuckDB results never enter a score. The table above lists the known
differences (integer division, `AVG(int)`, `DATEADD` return type, time-zone names, case-sensitive string
comparison, NULL ordering, decimal precision, `FORMAT` and `CONVERT` styles, `LIMIT` acceptance). Acceptance: at
least 80 % of the 64 row intents (70 intents minus 6 abstention intents) match, at least 15 of them
non-trivially; skipped intents carry their reason in `reports/parity.md` and in the question's `duckdb` field.
