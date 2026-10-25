# Fehlerklassen / Error taxonomy

Jede falsche Antwort bekommt genau eine Klasse. Automatisch vergeben `taxonomy.auto_labels` die Klassen E0, E1,
E2, E10, E11, E12 und E13; alle übrigen falschen Antworten tragen zunächst `E?` und werden für die
Leitkonfigurationen von Hand mit E3 bis E9 kategorisiert (`esb label <run_id>` legt die Zeilen in
`analysis/labels.csv` an; `esb report` führt sie zusammen).

| Klasse | Bedeutung | Beispiel | Vergabe |
|---|---|---|---|
| E0 | Providerfehler (Netz, Überlast, API-Fehler nach Wiederholungen) | HTTP 529 | automatisch |
| E1 | Syntax oder Dialekt | `LIMIT 10` statt `TOP 10`, kein SQL-Block | automatisch |
| E2 | erfundene Tabelle oder Spalte | `erzeugung_gwh` statt `erzeugung_mwh` | automatisch |
| E3 | falscher oder fehlender Join, Vervielfachung | Kapazität mit Erzeugung je Stunde verknüpft | Hand |
| E4 | falsche Granularität oder Aggregation | Mittel der Tagesmittel statt Mittel der Stunden | Hand |
| E5 | Zeitlogik | UTC statt lokaler Zeit, Zeitumstellung, Periodengrenzen, ISO-Woche | Hand |
| E6 | Wert oder Synonym | „Solar“ statt `Photovoltaik`, Name statt Kürzel, Kategorie | Hand |
| E7 | Einheit oder Skala | MWh statt GWh, kW statt MW, Anteil statt Prozent | Hand |
| E8 | NULL-Behandlung | `COUNT(*)` statt `COUNT(spalte)`, Kernenergie-Lücke | Hand |
| E9 | Sortierung oder Begrenzung | falsche Reihenfolge bei `ordered: true`, `TOP` zu klein | Hand |
| E10 | Form der Projektion | weniger Spalten als das Gold-Ergebnis | automatisch |
| E11 | vom Guard blockiert | `DELETE`, `sys.`-Abfrage, Schema `stg` | automatisch |
| E12 | Enthaltungsfehler | Enthaltung bei beantwortbarer Frage oder Antwort bei Frage der Klasse A | automatisch |
| E13 | Timeout oder Zeilenlimit | mehr als 10.000 Zeilen, mehr als 30 s | automatisch |

Regeln für die Handkategorisierung: die früheste Ursache im Abfrageplan zählt (ein falscher Join, der auch die
Summe verfälscht, ist E3, nicht E4); bei Zweifel zwischen Fachfehler und Gold-Fehler wird die Frage in
`docs/failures.md` als möglicher Gold-Fehler markiert und vom Eigentümer geprüft.

---

**English summary.** Every wrong answer gets one class. E0 provider error, E1 syntax or dialect, E2 hallucinated
table or column, E10 projection shape, E11 blocked by the guard, E12 abstention error and E13 timeout or row cap
are assigned automatically; E3 join, E4 grain or aggregation, E5 time logic, E6 value or synonym, E7 unit or
scale, E8 NULL handling and E9 ordering or limit are assigned by hand for the headline configurations through
`esb label` and `analysis/labels.csv`. The earliest cause in the query plan wins; suspected gold errors are flagged
in `docs/failures.md`.
