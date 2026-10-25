# Energie-SQL-Bench

How well do language models answer domain questions about the German power market with T-SQL on a real star
schema? Energie-SQL-Bench is a reproducible text-to-SQL benchmark in German and English on the SQL Server
warehouse of the [Energiewende-Monitor](https://github.com/HARISPAARTAN/energiewende-monitor): 70 intents with gold
SQL and frozen gold result sets, execution-based scoring, guarded read-only execution and recorded responses from
which CI re-derives every published number offline.

Results page: https://harispaartan.github.io/energie-sql-bench/en.html · Deutsch: [README.md](README.md)

## Summary

<!-- esb:headline:start -->
v4 = full schema + semantic layer + few-shot, single shot, test split (120 items).

| Model | EX (95 % CI) | Validity | USD per correct answer | Run |
|---|---|---|---|---|
| Claude Haiku 5.5 | pending: live run | – | – | – |
| Claude Sonnet 5.5 | pending: live run | – | – | – |
| Claude Opus 5.5 | pending: live run | – | – | – |
| Qwen2.5-Coder 7B (Ollama) | pending: live run | – | – | – |

- Pipeline test (synthetic, no language model): `synthetic-v4-test` (single shot) EX 68.3 % (82/120), tests the harness only, not a model result.
- Pipeline test (synthetic, no language model): `synthetic-v4-test-sc` (self-correction) EX 92.5 % (111/120), tests the harness only, not a model result.
<!-- esb:headline:end -->

## Results

v0.1.0 ships the question set, gold results, harness, replay and sample, but **no live run yet**: every model row
reads "pending: live run", and numbers are never estimated. The runs `synthetic-v4-test` and
`synthetic-v4-test-sc` are a pipeline test without a language model (answers from the gold SQL with fixed injected
faults); they show that guard, execution, comparison, self-correction, scoring and replay work together and say
nothing about any model. Full table: [`reports/leaderboard.en.md`](reports/leaderboard.en.md).

The first real run (owner, paid, prints a cost estimate first):

```powershell
uv run esb run --provider anthropic --model claude-haiku-5-5 --variant v4 --split dev --max-usd 0.50
```

Then the test-split runs, `uv run esb report`, commit the runs and tag `v0.2.0` (see below).

## Method

Six prompt variants (full schema, with semantic layer, with few-shot examples, oracle tables, retrieved tables),
scoring by comparing result sets with tolerance (EX and EX-strict), a semantic layer with 26 measures, a Wilson interval with one repeat and a question-level bootstrap interval with
several (repeats of the same item are not independent), exact McNemar tests on the per-item majority outcome, three
repeats per Claude configuration. Details: [`docs/methodology.md`](docs/methodology.md).

## Question set

70 intents × German and English = 140 items; `q001` to `q060` are scored (120 items: T1 12, T2 16, T3 16, T4 11,
unanswerable 5), `q061` to `q070` are development and few-shot questions. Every answerable question has an
independent check query (`check_sql`). Files: `bench/questions/`, `bench/gold/`.

## Safety

Login `bench_reader` with `SELECT` on `dw` and `rpt` only; a guard on the sqlglot AST lets exactly one read-only
statement through and fails closed; 30 s timeout, `SET LOCK_TIMEOUT 5000`, 10,000-row cap. `tests/db` sends
`DELETE`, `CREATE TABLE` and reads from `stg` past the guard straight to the database and expects permission
errors.

## Cost

Every run prints a cost estimate first, stops above `--max-usd` and computes the actual cost from recorded tokens
(including cache write and read tokens). Planning figure: a full sweep costs about 1 USD with Claude Haiku 5.5 and
about 8 USD with Sonnet 5.5 with prompt caching. Prices: [`pricing.toml`](pricing.toml).

## What did not work

- The first guard let `SELECT SUSER_SNAME()` through: sqlglot reads the function as `CURRENT_USER`. Functions that
  reveal session or server data are now on the deny list.
- `LIMIT` is valid in DuckDB, so the synthetic dialect fault cannot be reproduced on the CI sample and is left out
  of the end-to-end test.
- Keyword table retrieval (variant v6) picks the calendar tables too often because words such as "year" and "day"
  appear in almost every question.

## Limitations

- No live runs yet: statements about models follow with v0.2.0.
- The Anthropic adapter streams; the Batch API is not implemented.
- One warehouse, one bidding zone (DE-LU), data from 2023; the questions are tailored to this schema.
- The question set is public from release; later models may have seen it. Every run is dated.
- Gold results are double-checked but written by one person; the owner's review of 20 intents is pending.
- The DuckDB sample covers 64 of 64 (100.0 %) row intents, 23 of them non-trivially (a value that is neither NULL
  nor 0); 0 intents are skipped ([`reports/parity.md`](reports/parity.md)). Trivial matches (empty, NULL-only or
  zero-only results) only show that the translated query runs.
- A lenient comparison could flatter results; EX-strict is therefore shown next to EX.

## Quick start

```powershell
uv sync --locked
uv run pytest -q
uv run esb replay --all
uv run esb report --check
uv run esb guard-check "SELECT TOP 5 * FROM dw.fact_preis"
```

## Reproduce

Setup with the local database and read-only login: [`docs/setup-windows.md`](docs/setup-windows.md). Then
`uv run esb snapshot --check`, `uv run esb gold build`, and for a paid run for example
`uv run esb run --provider anthropic --model claude-haiku-5-5 --variant v4 --max-usd 2`.

## Data sources and licences

- Code: MIT ([`LICENSE`](LICENSE)). Question set and gold results: CC BY 4.0 ([`LICENSE-DATA.md`](LICENSE-DATA.md)).
- Bundesnetzagentur | SMARD.de (CC BY 4.0)
- Datenquelle: Marktstammdatenregister der Bundesnetzagentur, Datenlizenz Deutschland – Namensnennung – Version 2.0 (https://www.govdata.de/dl-de/by-2-0), Daten aggregiert.
- `data/sample/` (a Parquet slice of these sources and the gold results on it) is not MIT: it stays under the licences
  of the sources, with a change notice in [`LICENSE-DATA.md`](LICENSE-DATA.md) and
  [`data/sample/README.md`](data/sample/README.md).

## Next steps for the owner

1. **Anthropic credit and spend limit.** In the Anthropic Console buy the minimum credit, set a spend limit (for
   example $20 per month) and a workspace `energie-sql-bench` with its own limit, create an API key.
2. **Key in `.env`.** Put `ANTHROPIC_API_KEY=...` into the git-ignored `.env` of this repository (never commit it).
3. **Optional: Ollama as a free local baseline.** Install Ollama for Windows and run `ollama pull qwen2.5-coder:7b`.
   The NVIDIA RTX 4070 Ti SUPER with 16 GB VRAM runs 7B to 14B models; `qwen2.5-coder:14b` would be a second local
   baseline (add a pricing row with zeros to `pricing.toml` and a planned row to `config.toml`).
4. **Review of 20 gold intents.** Read `bench/questions/q001.yaml` to `q020.yaml` with their results in `bench/gold/`,
   note disagreements in an issue; confirmed fixes go through `esb gold build --only qNNN`.
5. **Live sweeps that become v0.2.0.** Smoke test on the dev split first (command above), then the planned
   configurations, for example `uv run esb run --provider anthropic --model claude-haiku-5-5 --variant v1 --repeat 3 --max-usd 2`,
   the same for v2 to v6 and `--self-correct`, Sonnet v1 to v6, Opus v4 and Ollama v4 and v5. Afterwards
   `uv run esb label <run_id>`, fill `analysis/labels.csv`, annotate 30 failures in `docs/failures.md`,
   `uv run esb report`, commit the runs, tag `v0.2.0`.

## Decisions

[ADR-001 provider](docs/decisions/ADR-001-provider.md) ·
[ADR-002 CI via replay and DuckDB](docs/decisions/ADR-002-ci-replay-duckdb.md) ·
[ADR-003 comparison rules](docs/decisions/ADR-003-comparison-rules.md) ·
[ADR-004 snapshot](docs/decisions/ADR-004-snapshot.md) ·
[ADR-005 no agent framework](docs/decisions/ADR-005-no-agent-framework.md) ·
[error classes](docs/taxonomy.md) · [failure analysis](docs/failures.md) · [dialect gap](docs/dialect-gap.md)
