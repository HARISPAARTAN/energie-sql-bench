# Leaderboard Energie-SQL-Bench v0.1.0

Erzeugt von `uv run esb report` aus den Aufzeichnungen unter `results/runs/`; CI berechnet jede Zahl offline neu.
Datenstand: SMARD 2023-01-01 – 2026-09-30, MaStR bis 2026-09, Stichtag 2026-10-01, Monitor-Commit `b399d01`.
Fragenkatalog: 70 Intents, 140 Items (DE und EN), davon 120 bewertet (Testsplit).

> Noch kein Live-Lauf: Jede Modellzeile steht auf „ausstehend: Live-Lauf“. Die ersten bezahlten Läufe erscheinen mit v0.2.0. Zahlen werden nie geschätzt.

## Konfigurationen

| Konfiguration | EX (95 %-KI) | Spanne | EX-strict | Validität | blockiert | Enthaltung P / R | LLM p50 / p95 ms | DB p50 / p95 ms | Tokens | USD pro richtige Antwort | Lauf |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Claude Haiku 5.5 · v1 (volles Schema) | ausstehend: Live-Lauf | – | – | – | – | – | – | – | – | – | – |
| Claude Haiku 5.5 · v2 (volles Schema + Few-Shot) | ausstehend: Live-Lauf | – | – | – | – | – | – | – | – | – | – |
| Claude Haiku 5.5 · v3 (volles Schema + Semantik) | ausstehend: Live-Lauf | – | – | – | – | – | – | – | – | – | – |
| Claude Haiku 5.5 · v4 (volles Schema + Semantik + Few-Shot) | ausstehend: Live-Lauf | – | – | – | – | – | – | – | – | – | – |
| Claude Haiku 5.5 · v5 (Orakel-Tabellen + Semantik + Few-Shot) | ausstehend: Live-Lauf | – | – | – | – | – | – | – | – | – | – |
| Claude Haiku 5.5 · v6 (abgerufene Tabellen + Semantik + Few-Shot) | ausstehend: Live-Lauf | – | – | – | – | – | – | – | – | – | – |
| Claude Haiku 5.5 · v4 (volles Schema + Semantik + Few-Shot) · Selbstkorrektur | ausstehend: Live-Lauf | – | – | – | – | – | – | – | – | – | – |
| Claude Sonnet 5.5 · v1 (volles Schema) | ausstehend: Live-Lauf | – | – | – | – | – | – | – | – | – | – |
| Claude Sonnet 5.5 · v2 (volles Schema + Few-Shot) | ausstehend: Live-Lauf | – | – | – | – | – | – | – | – | – | – |
| Claude Sonnet 5.5 · v3 (volles Schema + Semantik) | ausstehend: Live-Lauf | – | – | – | – | – | – | – | – | – | – |
| Claude Sonnet 5.5 · v4 (volles Schema + Semantik + Few-Shot) | ausstehend: Live-Lauf | – | – | – | – | – | – | – | – | – | – |
| Claude Sonnet 5.5 · v5 (Orakel-Tabellen + Semantik + Few-Shot) | ausstehend: Live-Lauf | – | – | – | – | – | – | – | – | – | – |
| Claude Sonnet 5.5 · v6 (abgerufene Tabellen + Semantik + Few-Shot) | ausstehend: Live-Lauf | – | – | – | – | – | – | – | – | – | – |
| Claude Opus 5.5 · v4 (volles Schema + Semantik + Few-Shot) | ausstehend: Live-Lauf | – | – | – | – | – | – | – | – | – | – |
| Qwen2.5-Coder 7B (Ollama) · v4 (volles Schema + Semantik + Few-Shot) | ausstehend: Live-Lauf | – | – | – | – | – | – | – | – | – | – |
| Qwen2.5-Coder 7B (Ollama) · v5 (Orakel-Tabellen + Semantik + Few-Shot) | ausstehend: Live-Lauf | – | – | – | – | – | – | – | – | – | – |

EX: Anteil der Items, deren Ergebnismenge der Gold-Ergebnismenge entspricht (zusätzliche Spalten erlaubt); EX-strict: gleiche Spaltenzahl. Spanne: Minimum und Maximum über Wiederholungen. Kosten in USD aus aufgezeichneten Token; EUR zum Kurs 1,1193 USD/EUR vom 2026-10-23.

Wiederholungen desselben Items sind nicht unabhängig. Die Genauigkeit wird zuerst je Item über die Wiederholungen gemittelt. Bei einer Wiederholung gilt das Wilson-Intervall (95 %) über die Items, bei mehreren ein Bootstrap-Intervall (95 %, feste Saat) über die Fragen. McNemar-Tests laufen auf dem Mehrheitsergebnis je Item (mehr als die Hälfte der Wiederholungen richtig).

## Gepaarte Vergleiche (exakter McNemar-Test)

| A | B | Paare | nur A richtig | nur B richtig | p |
|---|---|---|---|---|---|
| Claude Haiku 5.5 · v1 (volles Schema) | Claude Haiku 5.5 · v4 (volles Schema + Semantik + Few-Shot) | – | – | – | ausstehend: Live-Lauf |
| Claude Haiku 5.5 · v4 (volles Schema + Semantik + Few-Shot) | Claude Haiku 5.5 · v4 (volles Schema + Semantik + Few-Shot) · Selbstkorrektur | – | – | – | ausstehend: Live-Lauf |
| Claude Sonnet 5.5 · v1 (volles Schema) | Claude Sonnet 5.5 · v4 (volles Schema + Semantik + Few-Shot) | – | – | – | ausstehend: Live-Lauf |

## Pipeline-Test (synthetisch, kein Sprachmodell)

Diese Läufe enthalten kein Sprachmodell. Ein deterministischer Generator antwortet aus dem Gold-SQL und baut feste, markierte Fehler ein (Dialektfehler, erfundene Spalte, `DELETE`, falsche Enthaltung). Sie prüfen Guard, Ausführung, Vergleich, Selbstkorrektur, Bewertung und Replay und sind kein Modellergebnis.

| Lauf | Modus | EX | EX-strict | blockierte Versuche | Reparaturen | Fehlerklassen |
|---|---|---|---|---|---|---|
| `synthetic-v4-test` | Einzelversuch | 68,3 % (82/120) | 68,3 % | 10 | 0 | E1 8, E2 11, E11 10, E12 9 |
| `synthetic-v4-test-sc` | Selbstkorrektur | 92,5 % (111/120) | 92,5 % | 10 | 29 | E12 9 |

## Fehlerklassen

| Klasse | Bedeutung | `synthetic-v4-test` | `synthetic-v4-test-sc` |
|---|---|---|---|
| E1 | Syntax oder Dialekt | 8 | 0 |
| E2 | erfundene Tabelle oder Spalte | 11 | 0 |
| E11 | vom Guard blockiert | 10 | 0 |
| E12 | Enthaltungsfehler | 9 | 9 |

E0, E1, E2, E10, E11, E12 und E13 werden automatisch vergeben, E3 bis E9 von Hand (`esb label`, `analysis/labels.csv`). Details: `docs/taxonomy.md`.

## Fragenkatalog

| Tier | Test | Dev |
|---|---|---|
| A | 5 | 1 |
| T1 | 12 | 2 |
| T2 | 16 | 2 |
| T3 | 16 | 3 |
| T4 | 11 | 2 |

## DuckDB-Parität der CI-Stichprobe

64 von 64 Intents mit Ergebnis stimmen überein (100,0 %), davon 23 nicht trivial; 0 übersprungen. Details: `reports/parity.md`, `docs/dialect-gap.md`.
