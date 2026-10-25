# ADR-004: Datenstand und Schnitt / Snapshot and data cut

Status: angenommen, 2026-10-25

**Kontext.** Der Monitor lädt laufend nach; Gold-Ergebnisse gelten nur für einen festen Datenstand. Eine
Erweiterung bis 2015 wäre eine Entscheidung des Monitors und kein Gewinn für den Benchmark.

**Entscheidung.** Eingefroren: SMARD 2023-01-01 bis 2026-09-30, MaStR bis 2026-09, Monitor-Commit `b399d01`,
Stichtag 2026-10-01. `snapshot/fingerprint.json` hält den Stand fest; `esb run` und `esb gold build` brechen bei
Abweichung ab. Fragen nennen ihre Zeiträume ausdrücklich. Ein neuer Datenstand ist eine neue Benchmark-Version.

**Folgen.** Ergebnisse bleiben vergleichbar; wer den Monitor neu lädt, kann nicht versehentlich gegen andere
Daten messen.

*English: frozen, fingerprinted data cut; runs refuse to start on drift; a new cut is a new benchmark version.*
