# ADR-002: CI über Replay und DuckDB-Stichprobe / CI via replay and DuckDB

Status: angenommen, 2026-10-25

**Kontext.** CI soll jede veröffentlichte Zahl prüfen, aber ohne SQL Server, Netz und API-Schlüssel laufen.

**Entscheidung.** Jeder Lauf zeichnet Antworten und Ergebnismengen auf; `esb replay --all` bewertet sie in CI
neu und muss `summary.json` exakt treffen. Zusätzlich prüft eine DuckDB-Kopie einer kleinen Stichprobe, ob das
nach DuckDB übersetzte Gold-SQL dieselben Zeilen liefert wie SQL Server auf derselben Stichprobe.

**Verworfen.** Nur-Schema-Modus (prüft keine Ergebnisse); SQL-Server-Container pro Push (langsam, Lizenz- und
Datenfragen).

**Folgen.** Änderungen an Prompt, Vergleich oder Bewertung brechen das Replay sichtbar. Die Dialekt-Lücke ist in
`docs/dialect-gap.md` dokumentiert; DuckDB-Ergebnisse fließen nie in eine Bewertung ein.

*English: CI replays recorded responses and result sets and checks gold parity on a DuckDB sample; no SQL Server,
network or keys in CI.*
