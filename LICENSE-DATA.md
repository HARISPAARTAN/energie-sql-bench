# Lizenzen für Daten und Fragenkatalog / Data and question-set licences

## Fragenkatalog und Gold-Ergebnisse / Question set and gold results

Die Dateien unter `bench/` (Fragen, Gold-SQL, Gold-Ergebnisse, Few-Shot-Auswahl) stehen unter
Creative Commons Namensnennung 4.0 International (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/.
Namensnennung: "Energie-SQL-Bench, Harithas Harikaran".

Herkunft: Fragen, Gold-SQL und Gegenprobe-Abfragen hat ein Sprachmodell (Claude Sonnet 5.5, über Claude Code) nach Vorgaben des Eigentümers entworfen; sie sind durch Ausführung am Warehouse geprüft, die Prüfung von 20 Intents durch den Eigentümer steht aus (siehe `README.md`, „Herkunft des Goldstandards“).

The files under `bench/` are licensed under CC BY 4.0 (link above). Attribution: "Energie-SQL-Bench, Harithas Harikaran".

Provenance: the questions, gold SQL and check queries were drafted by a language model (Claude Sonnet 5.5 through Claude Code) under the owner's specification and verified by execution against the warehouse; the owner's review of 20 intents is pending (see `README.en.md`, "Provenance of the gold set").

## Quelldaten / Source data

Die Gold-Ergebnisse (`bench/gold/`) sind aus folgenden Daten abgeleitet / The gold results (`bench/gold/`) are derived from:

- SMARD (Strommarktdaten), Lizenz CC BY 4.0, Quellenangabe: `Bundesnetzagentur | SMARD.de`
- Datenquelle: Marktstammdatenregister der Bundesnetzagentur, Datenlizenz Deutschland – Namensnennung – Version 2.0 (https://www.govdata.de/dl-de/by-2-0), Daten aggregiert.

## CI-Stichprobe `data/sample/` / CI sample `data/sample/`

Die Dateien unter `data/sample/` (Parquet-Tabellen, `duckdb_views.sql`, `gold_mssql/*.json`, `manifest.json`,
`parity.json`) enthalten Zeilen der unten genannten Quellen und stehen **nicht** unter der MIT-Lizenz, sondern
unter den Lizenzen der Quellen. Sie sind ein Ausschnitt (ISO-Wochen 24/2025 und 43/2025 der Zeitreihen, die
Kapazitätsmonate 2026-07 bis 2026-09, Kalender 2025 und 2026, übrige Dimensionen vollständig) des
Energiewende-Warehouses, das aus diesen Quellen gebaut ist. Änderungen gegenüber den Quelldaten: Auswahl und
Aggregation (die Kapazität ist je Bundesland und Energieträger zusammengefasst), Typumwandlung (SQL Server nach
Parquet), rechts getrimmte Kürzel; die Gold-JSON-Dateien sind Abfrageergebnisse darauf.

- Bundesnetzagentur | SMARD.de (CC BY 4.0, https://creativecommons.org/licenses/by/4.0/)
- Datenquelle: Marktstammdatenregister der Bundesnetzagentur, Datenlizenz Deutschland – Namensnennung – Version 2.0 (https://www.govdata.de/dl-de/by-2-0), Daten aggregiert.

The files under `data/sample/` (Parquet tables, `duckdb_views.sql`, `gold_mssql/*.json`, `manifest.json`,
`parity.json`) contain rows of the sources named above and are **not** MIT-licensed; they stay under the
licences of those sources, with the attributions above. They are a slice (ISO weeks 24/2025 and 43/2025 of the
time series, capacity months 2026-07 to 2026-09, calendar 2025 and 2026, the other dimensions in full) of a
warehouse built from those sources. Changes to the source data: selection and aggregation (capacity is summed per
federal state and energy carrier), type conversion (SQL Server to Parquet), right-trimmed codes; the gold JSON
files are query results on the slice. The files contain no personal data.

## Code

Der Code steht unter der MIT-Lizenz (`LICENSE`). / The code is MIT-licensed (`LICENSE`).
