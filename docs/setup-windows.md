# Einrichtung unter Windows / Setup on Windows

Voraussetzungen: Docker Desktop mit dem geladenen Energiewende-Monitor (Container `ewm-mssql`, Port 1433),
Microsoft ODBC Driver 18 for SQL Server, uv 0.11.8, Git, GitHub CLI. Python 3.13 installiert uv selbst.

## 1. Repository und Umgebung

```powershell
git clone https://github.com/HARISPAARTAN/energie-sql-bench.git
cd energie-sql-bench
uv sync --locked
uv run esb version
```

Der Monitor muss als Geschwisterordner `..\energiewende-monitor` mit seiner `.env` vorhanden sein.

## 2. Nur-Lese-Login `bench_reader`

```powershell
uv run --env-file ../energiewende-monitor/.env python tools/setup_reader.py
```

Das Skript liest das `sa`-Passwort aus der `.env` des Monitors (es wird nie ausgegeben), erzeugt ein zufälliges
Passwort für `bench_reader` in der git-ignorierten `.env` dieses Repositorys und vergibt nur `SELECT` auf `dw`
und `rpt`. Prüfen: `uv run pytest -m db tests/db -q`. Entfernen:
`uv run --env-file ../energiewende-monitor/.env python tools/setup_reader.py --drop`.

## 3. Datenstand prüfen und Offline-Tests

```powershell
uv run esb snapshot --check
uv run pytest -q
uv run esb replay --all
uv run esb report --check
```

## 4. Live-Läufe (kostenpflichtig, nur durch den Eigentümer)

`ANTHROPIC_API_KEY=...` in `.env` eintragen, im Anthropic-Konto ein Ausgabelimit setzen, dann zuerst den
Dev-Split: `uv run esb run --provider anthropic --model claude-haiku-5-5 --variant v4 --split dev --max-usd 0.50`.
Jeder Lauf zeigt vorab eine Kostenschätzung und bricht über `--max-usd` ab.

Lokales Modell ohne API-Kosten: Ollama für Windows installieren, `ollama pull qwen2.5-coder:7b`, dann
`uv run esb run --provider ollama --variant v4`.

## Fehlerbilder

| Meldung | Ursache | Abhilfe |
|---|---|---|
| `Data source name not found` | ODBC Driver 18 fehlt | Treiber installieren |
| `Login failed for user 'bench_reader'` | Login fehlt oder `.env` veraltet | Schritt 2 wiederholen |
| `Snapshot weicht ab` | Monitor-Datenbank neu geladen | Datenstand des Monitors wiederherstellen; neuer Datenstand bedeutet neue Benchmark-Version |
| `ReplayMiss` | Prompt, Schema oder Code seit der Aufzeichnung geändert | Änderung zurücknehmen oder den Lauf neu aufzeichnen |

---

**English summary.** Install Docker Desktop with the monitor database, ODBC Driver 18, uv, Git and the GitHub CLI;
`uv sync --locked`; create the read-only login with `tools/setup_reader.py` (the `sa` password is read from the
monitor's `.env` and never printed); check the snapshot and run the offline tests; paid live runs need an API key
in `.env`, a spend limit and start on the dev split.
