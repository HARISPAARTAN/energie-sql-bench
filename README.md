# Energie-SQL-Bench

Wie gut beantworten Sprachmodelle Fachfragen zum deutschen Strommarkt mit T-SQL auf einem echten Sternschema?
Energie-SQL-Bench ist ein reproduzierbarer Text-to-SQL-Benchmark auf Deutsch und Englisch auf dem
SQL-Server-Warehouse des [Energiewende-Monitors](https://github.com/HARISPAARTAN/energiewende-monitor):
70 Intents mit Gold-SQL und eingefrorenen Gold-Ergebnissen, ausführungsbasierte Bewertung, abgesicherte
Nur-Lese-Ausführung und aufgezeichnete Antworten, aus denen CI jede veröffentlichte Zahl offline neu berechnet.

Ergebnisseite: https://harispaartan.github.io/energie-sql-bench/ · English: [README.en.md](README.en.md)

## Kurzfassung

<!-- esb:headline:start -->
v4 = volles Schema + Semantik + Few-Shot, Einzelversuch, Testsplit (120 Items).

| Modell | EX (95 %-KI) | Validität | USD pro richtige Antwort | Lauf |
|---|---|---|---|---|
| Claude Haiku 5.5 | ausstehend: Live-Lauf | – | – | – |
| Claude Sonnet 5.5 | ausstehend: Live-Lauf | – | – | – |
| Claude Opus 5.5 | ausstehend: Live-Lauf | – | – | – |
| Qwen2.5-Coder 7B (Ollama) | ausstehend: Live-Lauf | – | – | – |

- Pipeline-Test (synthetisch, kein Sprachmodell): `synthetic-v4-test` (Einzelversuch) EX 68,3 % (82/120), prüft nur die Harness, kein Modellergebnis.
- Pipeline-Test (synthetisch, kein Sprachmodell): `synthetic-v4-test-sc` (Selbstkorrektur) EX 92,5 % (111/120), prüft nur die Harness, kein Modellergebnis.
<!-- esb:headline:end -->

## Ergebnisse

v0.1.0 liefert Fragenkatalog, Gold-Ergebnisse, Harness, Replay und Stichprobe, aber **noch keinen Live-Lauf**:
jede Modellzeile steht auf „ausstehend: Live-Lauf“, Zahlen werden nie geschätzt. Die beiden Läufe
`synthetic-v4-test` und `synthetic-v4-test-sc` sind ein Pipeline-Test ohne Sprachmodell (Antworten aus dem
Gold-SQL mit fest eingebauten Fehlern); sie beweisen, dass Guard, Ausführung, Vergleich, Selbstkorrektur,
Bewertung und Replay zusammen funktionieren, und sagen nichts über ein Modell. Vollständige Tabelle:
[`reports/leaderboard.md`](reports/leaderboard.md).

Der erste echte Lauf (Eigentümer, kostenpflichtig, mit Kostenschätzung vorab):

```powershell
uv run esb run --provider anthropic --model claude-haiku-5-5 --variant v4 --split dev --max-usd 0.50
```

Danach die Testläufe, `uv run esb report`, Läufe committen und `v0.2.0` taggen (siehe unten).

## Methode

Sechs Prompt-Varianten (volles Schema, mit Semantik-Schicht, mit Few-Shot-Beispielen, Orakel-Tabellen,
abgerufene Tabellen), Bewertung über den Vergleich der Ergebnismengen mit Toleranz (EX und EX-strict),
eine Semantik-Schicht mit 26 Kennzahlen, Wilson-Intervall bei einer Wiederholung und Bootstrap-Intervall über die
Fragen bei mehreren (Wiederholungen desselben Items sind nicht unabhängig), exakte McNemar-Tests auf dem
Mehrheitsergebnis je Item, drei Wiederholungen je Claude-Konfiguration. Details:
[`docs/methodology.md`](docs/methodology.md).

## Fragenkatalog

70 Intents × Deutsch und Englisch = 140 Items; `q001` bis `q060` werden bewertet (120 Items: T1 12, T2 16,
T3 16, T4 11, nicht beantwortbar 5), `q061` bis `q070` sind Entwicklungs- und Few-Shot-Fragen. Jede
beantwortbare Frage hat eine unabhängige Gegenprobe (`check_sql`). Dateien: `bench/questions/`, `bench/gold/`.

## Sicherheit

Login `bench_reader` nur mit `SELECT` auf `dw` und `rpt`; ein Guard auf dem sqlglot-AST lässt genau eine lesende
Anweisung durch und blockiert im Zweifel; 30 s Timeout, `SET LOCK_TIMEOUT 5000`, 10.000 Zeilen Obergrenze.
`tests/db` schickt `DELETE`, `CREATE TABLE` und Zugriffe auf `stg` am Guard vorbei direkt an die Datenbank und
erwartet Rechtefehler.

## Kosten

Jeder Lauf zeigt vorab eine Kostenschätzung, bricht über `--max-usd` ab und berechnet die tatsächlichen Kosten aus
den aufgezeichneten Token (inklusive Cache-Schreib- und Lesetoken). Planungswert: ein vollständiger Durchlauf mit
Claude Haiku 5.5 kostet etwa 1 USD, mit Sonnet 5.5 etwa 8 USD mit Prompt-Caching. Preise: [`pricing.toml`](pricing.toml).

## Was nicht funktioniert hat

- Die erste Fassung des Guards ließ `SELECT SUSER_SNAME()` durch: sqlglot liest die Funktion als
  `CURRENT_USER`. Funktionen, die Sitzungs- oder Serverdaten preisgeben, stehen jetzt auf der Sperrliste.
- `LIMIT` ist in DuckDB gültig: der synthetische Dialektfehler lässt sich auf der CI-Stichprobe nicht nachstellen
  und wird im End-to-End-Test ausgelassen.
- Die Tabellenauswahl nach Stichworten (Variante v6) trifft Kalendertabellen zu oft, weil Wörter wie „Jahr“ und
  „Tag“ in fast jeder Frage vorkommen.

## Grenzen

- Noch keine Live-Läufe: Aussagen über Modelle folgen mit v0.2.0.
- Der Anthropic-Adapter nutzt Streaming; die Batch-API ist nicht umgesetzt.
- Ein Warehouse, eine Gebotszone (DE-LU), Daten ab 2023; die Fragen sind auf dieses Schema zugeschnitten.
- Der Fragenkatalog ist ab Veröffentlichung öffentlich; spätere Modelle können ihn gesehen haben. Jeder Lauf ist
  datiert.
- Gold-Ergebnisse sind doppelt geprüft, aber von einer Person geschrieben; die Prüfung von 20 Intents durch den
  Eigentümer steht aus.
- Die DuckDB-Stichprobe deckt 64 von 64 (100,0 %) Intents mit Ergebnis ab, davon 23 nicht trivial (Wert ungleich
  NULL und 0); 0 Intents sind übersprungen ([`reports/parity.md`](reports/parity.md)). Triviale Treffer
  (leeres Ergebnis, nur NULL oder nur 0) zeigen nur, dass die übersetzte Abfrage läuft.
- Ein großzügiger Vergleich könnte Ergebnisse schönen; deshalb steht EX-strict neben EX.

## Schnellstart

```powershell
uv sync --locked
uv run pytest -q
uv run esb replay --all
uv run esb report --check
uv run esb guard-check "SELECT TOP 5 * FROM dw.fact_preis"
```

## Reproduzieren

Einrichtung mit lokaler Datenbank und Nur-Lese-Login: [`docs/setup-windows.md`](docs/setup-windows.md). Dann
`uv run esb snapshot --check`, `uv run esb gold build`, und für einen bezahlten Lauf zum Beispiel
`uv run esb run --provider anthropic --model claude-haiku-5-5 --variant v4 --max-usd 2`.

## Datenquellen und Lizenzen

- Code: MIT ([`LICENSE`](LICENSE)). Fragenkatalog und Gold-Ergebnisse: CC BY 4.0 ([`LICENSE-DATA.md`](LICENSE-DATA.md)).
- Bundesnetzagentur | SMARD.de (CC BY 4.0)
- Datenquelle: Marktstammdatenregister der Bundesnetzagentur, Datenlizenz Deutschland – Namensnennung – Version 2.0 (https://www.govdata.de/dl-de/by-2-0), Daten aggregiert.
- `data/sample/` (Parquet-Ausschnitt dieser Quellen, Gold-Ergebnisse darauf) steht nicht unter MIT, sondern unter den
  Lizenzen der Quellen, mit Änderungshinweis in [`LICENSE-DATA.md`](LICENSE-DATA.md) und
  [`data/sample/README.md`](data/sample/README.md).

## Nächste Schritte für den Eigentümer

1. **Anthropic-Guthaben und Ausgabelimit.** In der Anthropic Console Mindestguthaben kaufen, ein Ausgabelimit
   (zum Beispiel 20 USD pro Monat) und einen eigenen Workspace `energie-sql-bench` mit Limit setzen, einen
   API-Schlüssel erzeugen.
2. **Schlüssel in `.env`.** `ANTHROPIC_API_KEY=...` in die git-ignorierte `.env` dieses Repositorys eintragen (nie
   committen).
3. **Optional: Ollama als kostenlose lokale Basislinie.** Ollama für Windows installieren und
   `ollama pull qwen2.5-coder:7b` ausführen. Die NVIDIA RTX 4070 Ti SUPER mit 16 GB VRAM trägt 7B- bis 14B-Modelle;
   `qwen2.5-coder:14b` wäre eine zweite lokale Basislinie (Preiszeile mit Nullen in `pricing.toml` und geplante Zeile
   in `config.toml` ergänzen).
4. **Prüfung von 20 Gold-Intents.** `bench/questions/q001.yaml` bis `q020.yaml` mit den Ergebnissen in `bench/gold/`
   lesen, Abweichungen in einem Issue notieren; bestätigte Korrekturen laufen über `esb gold build --only qNNN`.
5. **Live-Läufe, die zu v0.2.0 werden.** Zuerst der Dev-Split-Rauchtest (Befehl oben), dann die geplanten
   Konfigurationen, zum Beispiel `uv run esb run --provider anthropic --model claude-haiku-5-5 --variant v1 --repeat 3 --max-usd 2`,
   dasselbe für v2 bis v6 und `--self-correct`, Sonnet v1 bis v6, Opus v4 und Ollama v4 und v5. Danach
   `uv run esb label <run_id>`, `analysis/labels.csv` füllen, 30 Fehler in `docs/failures.md` annotieren,
   `uv run esb report`, Läufe committen, `v0.2.0` taggen.

## Entscheidungen

[ADR-001 Anbieter](docs/decisions/ADR-001-provider.md) ·
[ADR-002 CI über Replay und DuckDB](docs/decisions/ADR-002-ci-replay-duckdb.md) ·
[ADR-003 Vergleichsregeln](docs/decisions/ADR-003-comparison-rules.md) ·
[ADR-004 Datenstand](docs/decisions/ADR-004-snapshot.md) ·
[ADR-005 kein Agenten-Framework](docs/decisions/ADR-005-no-agent-framework.md) ·
[Fehlerklassen](docs/taxonomy.md) · [Fehleranalyse](docs/failures.md) · [Dialekt-Lücke](docs/dialect-gap.md)
