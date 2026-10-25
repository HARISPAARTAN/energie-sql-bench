# Fehleranalyse / Failure analysis

Status v0.1.1: **ausstehend: Live-Lauf.** Diese Datei wird mit den ersten echten Läufen (v0.2.0) gefüllt. Die
Pipeline-Test-Läufe `synthetic-v4-test` und `synthetic-v4-test-sc` enthalten kein Sprachmodell; ihre Fehler sind
absichtlich eingebaut und werden hier nicht annotiert.

Ziel für v0.2.0: mindestens 30 annotierte Fehler über die Leitkonfigurationen, jeder mit dem folgenden Aufbau.

## Vorlage

### qNNN-de · Lauf `<run_id>` · Wiederholung 0 · Klasse E5

- Frage: „…“
- Erzeugtes SQL:

```sql
SELECT …
```

- Unterschied zum Gold-Ergebnis: erwartet …, erhalten … (`esb replay` zeigt beide Ergebnismengen).
- Ursache: …
- Möglicher Gold-Fehler: nein / ja (Begründung, vom Eigentümer zu prüfen)

---

**English summary.** Status v0.1.1: pending a live run. From v0.2.0 this file annotates at least 30 failures of
the headline configurations with question, generated SQL, the difference to the gold result, the cause and a
possible-gold-error flag. The synthetic pipeline-test runs contain no language model and are not annotated.
