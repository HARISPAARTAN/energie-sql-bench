# Changelog

## v0.1.1 (2026-10-25)

Fixes from the final review of v0.1.0. No recorded model run, no gold file and no prompt changed; there is still no
live run.

- **Honesty (C1).** Both READMEs, `docs/methodology.md`, `LICENSE-DATA.md` and the results site no longer say the
  gold set was written by one person. Questions, gold SQL and check queries were drafted by a language model
  (`claude-sonnet-5-5` through Claude Code, tasks 3 and 4 on 2026-10-25 and 2026-10-26) and verified by execution
  against the warehouse; the owner's review of 20 intents is pending. `check_sql` is described as a second,
  model-written query compared by execution, not as an independent check. New section "Herkunft des Goldstandards"
  / "Provenance of the gold set".
- **Guard (I1).** CTE names are resolved in definition order: a reference to a CTE defined later in the same `WITH`
  list is an ordinary table reference and must pass the catalog and schema checks (it used to read the legacy
  catalog views, e.g. `WITH a AS (SELECT name FROM syslogins), syslogins AS (...) SELECT name FROM a`). The legacy
  compatibility views (`sysobjects`, `syslogins`, `sysusers`, `sysdatabases` and the other `sys*` names) are blocked
  explicitly. New cases in the malicious set and a live test as `bench_reader` that the block happens before
  execution. Docs state that the login inherits the `public` role.
- **Report (I2).** `esb report` publishes a run only if it is complete, on the test split, without `--limit`, in both
  languages, with all 120 scored items, the committed snapshot digest and the current prompt version. Other real
  runs are listed with the reason under "Nicht gewertete Läufe" and appear in no row.
- **Costs (I3).** README cost figures are recomputed with the code's own estimator (`tools/cost_plan.py`): upper
  bound 53.91 USD and cached expectation 19.27 USD for the 14 Claude configurations at three repeats, with the
  assumptions stated (items, repeats, tokens per prompt variant, thinking tokens not included). The suggested monthly
  limit is raised from 20 to 60 USD, with a staged plan and `--max-usd 8` for Sonnet v4.
- **Statistics (I4).** German and English items of one intent are paired. The 95 % interval is an intent-level
  bootstrap for every repeat count (Wilson over items for one repeat is gone), and the paired McNemar tests run over
  intents (an intent is correct when all its language items are correct by majority). `scoring.METHODOLOGY_NOTE`,
  the methodology page and the report columns say so; `summary_version` is 3 and the two synthetic recordings'
  `summary.json` were recomputed (responses and predictions are unchanged).
- Version bumped to 0.1.1.

## v0.1.0 (2026-10-25)

First release: 70 intents in German and English with frozen gold results, the guarded read-only harness, scoring,
recorded runs with offline replay, the DuckDB CI sample, the leaderboard and the results site. No live model run.
