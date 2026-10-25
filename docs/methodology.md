# Methode / Methodology

## Datenstand

Gemessen wird gegen die SQL-Server-2022-Datenbank `energiewende` des Energiewende-Monitors (Schemas `dw` und
`rpt`, Gebotszone DE-LU). Der Datenstand ist eingefroren: SMARD-Zeitreihen vom 2023-01-01 bis 2026-09-30
(lokale Daten), MaStR-Kapazität monatlich bis 2026-09 (Export vom 2026-10-25), Monitor-Commit `b399d01`,
Stichtag `as_of` 2026-10-01. `snapshot/fingerprint.json` hält Zeilenzahlen, Datumsgrenzen und Prüfsummen fest;
`esb run` und `esb gold build` verweigern die Arbeit, wenn die Live-Datenbank davon abweicht. Ein neuer
Datenstand ist eine neue Benchmark-Version.

## Fragen und Splits

70 Intents, jeder auf Deutsch und Englisch (140 Items). `q001` bis `q060` bilden den Testsplit (120 bewertete
Items), `q061` bis `q070` den Dev-Split; Few-Shot-Beispiele stammen nur aus dem Dev-Split (`q063 q064 q065 q068
q069 q070`), ein Unit-Test verhindert n-Gramm-Überlappung mit Testfragen. Tiers: T1 eine Tabelle, T2 Join oder
Filter mit Fachbegriff, T3 Zeitlogik oder mehrere Schritte, T4 Fensterfunktionen und Vergleiche, A nicht
beantwortbar (richtige Antwort: `NICHT_BEANTWORTBAR` oder ein leeres Ergebnis).

## Gold

Jede beantwortbare Frage hat `gold_sql` und eine zweite, ebenfalls modellgeschriebene Abfrage `check_sql`. `esb gold build`
führt beide aus, verlangt Gleichheit, Reproduzierbarkeit (zweimal ausgeführt), höchstens 1.000 Zeilen und ein
nicht leeres Ergebnis und speichert die Ergebnismenge in `bench/gold/qNNN.json` (Dezimalzahlen als Text).

### Herkunft des Goldstandards

Fragen (Deutsch und Englisch), Gold-SQL und `check_sql` aller 70 Intents hat ein Sprachmodell entworfen (Claude
Sonnet 5.5, `claude-sonnet-5-5`, über Claude Code, Aufgaben 3 und 4 am 2026-10-25) nach Vorgaben des
Eigentümers. Ein Mensch hat sie noch nicht durchgesehen; die Prüfung von 20 Intents durch den Eigentümer steht aus.
Geprüft ist durch Ausführung: das Gold läuft zweimal, `check_sql` ist eine zweite, ebenfalls modellgeschriebene
Abfrage und wird per Ausführung verglichen. Für etwa 18 Intents geht sie denselben Weg wie das Gold (Sichten und
Schlüssel statt Namen), fängt also ein gemeinsames Missverständnis der Frage nicht ab. Getrennte Prüf-Agenten
(ebenfalls Sprachmodelle) haben für mehr als 50 Intents eigene Abfragen geschrieben und gegen die Datenbank
verglichen; alle stimmten überein. Das ersetzt keine menschliche Prüfung.

## Varianten

| Variante | Schema | Semantik-Schicht | Few-Shot |
|---|---|---|---|
| v1 | voll | nein | nein |
| v2 | voll | nein | ja |
| v3 | voll | ja | nein |
| v4 | voll | ja | ja |
| v5 | Orakel-Tabellen der Gold-Abfrage | ja | ja |
| v6 | deterministisch abgerufene Tabellen | ja | ja |

Prompts werden deterministisch gebaut; ihr SHA-256 (`prompt_hash`) ist der Schlüssel für Replay.

## Ausführung und Bewertung

Antwort: genau ein ` ```sql `-Block oder `NICHT_BEANTWORTBAR`. Der Guard lässt nur eine lesende Anweisung auf
`dw` und `rpt` durch; ausgeführt wird als `bench_reader` mit 30 s Timeout, `SET LOCK_TIMEOUT 5000` und 10.000
Zeilen Obergrenze. Mit `--self-correct` gehen Guard-Block, Parserfehler und Datenbankfehler mit der Fehlermeldung
bis zu zweimal zurück an das Modell; falsche, aber gültige Ergebnisse werden nie zurückgemeldet (kein Gold-Leck).

Vergleich: Werte normalisiert (Zahlen als `Decimal`, relative Toleranz 1e-4 oder absolute 0,005, NULL gleich
NULL, Datum und Zeit ISO, Text NFC und getrimmt, `bit` als Zahl), Zeilen als Multimenge (sortiert nur bei
`ordered: true`), Spalten per bester Zuordnung ohne Namen. **EX** erlaubt zusätzliche Spalten, **EX-strict**
verlangt gleiche Spaltenzahl. Abgeschnittene Ergebnisse sind falsch. Einheiten werden nie umgerechnet.

## Statistik

EX getrennt nach Tier und Sprache; Validität (geparst, erlaubt, ausgeführt);
blockierte Versuche; Präzision und Recall der Enthaltung; Latenz p50/p95 von Modell und Datenbank; Token nach
Art; Kosten in USD aus aufgezeichneten Token (EUR zum datierten Kurs aus `config.toml`); Kosten pro richtiger
Antwort. Gepaarte Vergleiche (v1 gegen v4, Einzelversuch gegen Selbstkorrektur, DE gegen EN) mit exaktem
McNemar-Test. Claude-Konfigurationen laufen dreimal; berichtet werden Mittelwert und Spanne.

Das deutsche und das englische Item eines Intents sind gepaart, und Wiederholungen desselben Items sind nicht
unabhängig; die wirksame Stichprobe sind die 60 Intents des Testsplits, nicht die 120 Items. Die Genauigkeit wird
zuerst je Item über die Wiederholungen gemittelt. Das 95 %-Intervall ist bei jeder Wiederholungszahl ein
Bootstrap-Intervall über die Intents (feste Saat): Intents werden mit Zurücklegen gezogen und nehmen ihre deutschen
und englischen Items samt Wiederholungen mit. McNemar-Tests zwischen Konfigurationen laufen auf Intents: Ein Item
gilt als richtig, wenn mehr als die Hälfte seiner Wiederholungen richtig ist (bei Gleichstand falsch), ein Intent,
wenn alle seine Sprachitems richtig sind; die Paare sind Intents, nie Items und nie (Item, Wiederholung). DE gegen EN
innerhalb eines Laufs paart die beiden Sprachitems jedes Intents. Die gepoolten Zähler „richtig“ und „n“ sind Summen
über alle Wiederholungen und tragen kein Intervall. Der Wortlaut steht in `scoring.METHODOLOGY_NOTE` und wird vom
Leaderboard übernommen.

### Aufnahme in die Rangliste

Ein aufgezeichneter Lauf wird nur dann eine veröffentlichte Zeile, wenn er zur geplanten Konfiguration passt:
Testsplit, vollständig, ohne `--limit`, beide Sprachen, alle 120 bewerteten Items, derselbe Snapshot-Digest wie
`snapshot/fingerprint.json` und die aktuelle Prompt-Version. Alles andere (Rauchtests, einsprachige oder teilweise
Läufe, Läufe gegen einen älteren Snapshot) steht mit Grund unter „Nicht gewertete Läufe“ und erscheint in keiner Zeile.

## Reproduzierbarkeit

Jeder Lauf speichert `config.json`, `responses.jsonl` (alle Antworten mit Token und Latenz),
`predictions.jsonl.gz` (alle Ergebnismengen, Schlüssel SHA-256 des SQL) und `summary.json`. `esb replay --all`
berechnet jede Zusammenfassung offline neu und muss sie Byte für Byte treffen; `esb report --check` prüft
Leaderboard, Seite und README-Kurzfassung. Beides läuft in CI ohne Datenbank, Netz und API-Schlüssel.

---

**English summary.** The benchmark measures against a frozen, fingerprinted cut of the Energiewende-Monitor
warehouse (SMARD 2023-01-01 to 2026-09-30, MaStR to 2026-09). 70 intents in German and English; `q001` to `q060`
are scored (120 items), `q061` to `q070` are dev and the only source of few-shot examples. Gold results are
drafted by a language model (Claude Sonnet 5.5) and verified by execution (gold run twice, a second model-written check query compared by execution; the owner's review of 20 intents is pending) and stored. Six prompt variants ablate schema linking, the semantic layer
and few-shot examples. Predictions are guarded, executed read-only and compared as multisets with tolerance and
best column assignment (EX allows extra columns, EX-strict does not). The German and English item of an intent are paired and repeats are not independent, so accuracy carries an intent-level bootstrap interval for every repeat count and paired comparisons use the exact McNemar test on intents (an intent is correct when all its language items are correct by majority); Claude runs are repeated three times. Only complete, full-set runs that match the committed snapshot and prompt version become leaderboard rows. Every run is recorded so CI
re-derives every number offline.
