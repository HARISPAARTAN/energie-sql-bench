# ADR-003: Vergleichsregeln / Comparison rules

Status: angenommen, 2026-10-25

**Kontext.** Zeichenkettenvergleich von SQL bestraft richtige Alternativen; zu laxe Vergleiche blähen Ergebnisse.

**Entscheidung.** Ausführungsbasiert: Multimenge der Zeilen (Reihenfolge nur bei `ordered: true`), Spalten per
bester Zuordnung ohne Namen, relative Toleranz 1e-4 oder absolute 0,005, NULL gleich NULL, Text NFC und getrimmt,
Datum und Zeit ISO. EX erlaubt zusätzliche Spalten, EX-strict nicht; beide werden berichtet. Abgeschnittene
Ergebnisse sind falsch; Einheiten werden nie umgerechnet, die Frage nennt die Einheit.

**Folgen.** Ein Modell, das zusätzliche Kontextspalten liefert, wird nicht bestraft, EX-strict zeigt den
Unterschied. Eine Stichprobe von 30 als richtig gewerteten Antworten wird nach den Live-Läufen von Hand geprüft.

*English: execution-based multiset comparison with best column assignment and tolerance; EX and EX-strict.*
