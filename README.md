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

v0.1.1 liefert Fragenkatalog, Gold-Ergebnisse, Harness, Replay und Stichprobe, aber **noch keinen Live-Lauf**:
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
eine Semantik-Schicht mit 26 Kennzahlen, Bootstrap-Intervall über die Intents (das deutsche und das englische Item
eines Intents sind gepaart, Wiederholungen desselben Items nicht unabhängig), exakte McNemar-Tests auf Intents, drei
Wiederholungen je Claude-Konfiguration. Details:
[`docs/methodology.md`](docs/methodology.md).

## Fragenkatalog

70 Intents × Deutsch und Englisch = 140 Items; `q001` bis `q060` werden bewertet (120 Items: T1 12, T2 16,
T3 16, T4 11, nicht beantwortbar 5), `q061` bis `q070` sind Entwicklungs- und Few-Shot-Fragen. Jede
beantwortbare Frage hat neben der Gold-SQL eine zweite, ebenfalls modellgeschriebene Abfrage (`check_sql`), deren
Ergebnis per Ausführung mit dem Gold verglichen wird. Dateien: `bench/questions/`, `bench/gold/`.

## Herkunft des Goldstandards

Die Fragen (Deutsch und Englisch), die Gold-SQL und die Gegenprobe-Abfragen aller 70 Intents hat ein Sprachmodell
entworfen: Claude Sonnet 5.5 (`claude-sonnet-5-5`) über Claude Code, in den Aufgaben 3 und 4 am 2026-10-25,
nach Vorgaben des Eigentümers (Schema, Stufen, Konventionen). Ein Mensch hat sie bisher nicht
durchgesehen; die Prüfung von 20 Intents durch den Eigentümer steht aus.

Geprüft wurde durch Ausführung am Warehouse. Die Gold-SQL läuft zweimal (reproduzierbar, nicht leer, höchstens
1.000 Zeilen). Die Gegenprobe ist eine zweite Abfrage je Intent, ebenfalls vom Modell geschrieben, und wird per
Ausführung mit dem Gold verglichen; für etwa 18 Intents geht sie denselben Weg wie das Gold (Sichten und Schlüssel
statt Namen) und fängt ein gemeinsames Missverständnis der Frage deshalb nicht ab. Dazu haben getrennte Prüf-Agenten,
ebenfalls Sprachmodelle, für mehr als 50 Intents eigene Abfragen geschrieben und gegen die Datenbank verglichen
(alle stimmten überein). Das ist keine menschliche Prüfung. Bis sie vorliegt, sind die Gold-Ergebnisse als
modellentworfen und ausführungsgeprüft zu lesen; ein Fehler im Gold träfe alle Modelle gleich.

## Sicherheit

Login `bench_reader` nur mit `SELECT` auf `dw` und `rpt`; ein Guard auf dem sqlglot-AST lässt genau eine lesende
Anweisung durch und blockiert im Zweifel; 30 s Timeout, `SET LOCK_TIMEOUT 5000`, 10.000 Zeilen Obergrenze.
`tests/db` schickt `DELETE`, `CREATE TABLE` und Zugriffe auf `stg` am Guard vorbei direkt an die Datenbank und
erwartet Rechtefehler. Das Login erbt die Rechte der Rolle `public`: Metadaten der Systemkataloge und der
Gastzugriff auf master, msdb und tempdb bleiben auf Datenbankebene möglich; sie zu lesen verhindert der Guard (er
sperrt `sys.*`, `INFORMATION_SCHEMA`, die alten Kompatibilitätssichten wie `sysobjects` und Namen ohne Schema), nicht
das Login. Eine CTE gilt nur für Abfragen nach ihrer Definition; ein Verweis auf eine später definierte CTE ist eine
gewöhnliche Tabelle ohne Schema und wird blockiert.

## Kosten

Jeder Lauf zeigt vorab eine Kostenschätzung, bricht über `--max-usd` ab (Standard 5 USD je Lauf) und berechnet die
tatsächlichen Kosten aus den aufgezeichneten Token (inklusive Cache-Schreib- und Lesetoken). Preise:
[`pricing.toml`](pricing.toml). Planungswerte für den vollen Durchlauf der 14 Claude-Konfigurationen, berechnet mit
dem Schätzer des Codes (`uv run python tools/cost_plan.py`):

| Modell | Konfigurationen | obere Grenze (USD) | mit Cache, erwartet (USD) |
|---|---|---|---|
| Claude Haiku 5.5 | 7 (v1 bis v6, v4 mit Selbstkorrektur) | 2,38 | 0,89 |
| Claude Sonnet 5.5 | 6 (v1 bis v6) | 36,20 | 14,11 |
| Claude Opus 5.5 | 1 (v4) | 15,33 | 4,27 |
| Summe | 14 | 53,91 | 19,27 |

Annahmen: Testsplit mit 120 Items, drei Wiederholungen je Konfiguration, Selbstkorrektur mit Faktor 1,5, 500
Ausgabetoken je Aufruf, 3,5 Zeichen je Token. Der Prompt hat im Mittel etwa 4.020 (v1), 5.120 (v2), 7.050 (v3), 8.140
(v4), 5.370 (v5) und 5.580 Token (v6), davon nur etwa 35 Token Frage; der Rest ist ein statisches Systempräfix. Die
obere Grenze rechnet den ganzen Prompt zum normalen Eingabepreis; der erwartete Wert rechnet das Präfix einmal als
Cache-Schreibung und danach als Cache-Lesung (bei v5 und v6 wechselt das Präfix, 16 und 29 verschiedene), die Frage
zum Eingabepreis. Nicht enthalten sind Denk-Token (adaptives Thinking läuft ohne `thinking`-Angabe mit und wird als
Ausgabe berechnet), zusätzliche Cache-Schreibungen nach Pausen über fünf Minuten und Wiederholungen nach Fehlern.

Einzelne Läufe: Sonnet v4 mit drei Wiederholungen hat die obere Grenze 7,66 USD und braucht deshalb
`--max-usd 8`. Das Ausgabelimit bei Anthropic wählt der Eigentümer; für den ganzen Durchlauf passt ein Monatslimit
um 60 USD (obere Grenze 54 USD plus Denk-Token), gestuft weniger: zuerst Haiku (0,89 bis 2,38 USD), dann Sonnet v1
und v4 (4,55 bis 12,36 USD), dann der Rest.

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
- Der Goldstandard (Fragen, Gold-SQL, Gegenprobe) wurde von einem Sprachmodell entworfen und durch Ausführung am
  Warehouse geprüft, nicht von einem Menschen geschrieben; die Prüfung von 20 Intents durch den Eigentümer steht aus
  (siehe „Herkunft des Goldstandards“).
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
   (Vorschlag: 60 USD pro Monat für den ganzen Durchlauf, gestuft weniger, siehe „Kosten“) und einen eigenen Workspace
   `energie-sql-bench` mit Limit setzen, einen API-Schlüssel erzeugen.
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
