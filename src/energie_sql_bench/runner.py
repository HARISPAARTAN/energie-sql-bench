"""Run orchestration: prompt, provider, SQL extraction, guard, execution, scoring, recording and replay.

Every result set is passed through its JSON encoding before scoring, and identical SQL is executed once per
run, so a replay from the recorded files reproduces the live summary exactly."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import asdict, dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

from energie_sql_bench import __version__
from energie_sql_bench.config import CompareSettings, ModelPrice, Settings, VariantSpec
from energie_sql_bench.execute import ExecResult, Executor
from energie_sql_bench.files import dump_json, read_json
from energie_sql_bench.gold import GoldEntry, load_gold, sql_sha256
from energie_sql_bench.guard import check_sql
from energie_sql_bench.llm.base import Provider, ProviderError, Request
from energie_sql_bench.prompts import (
    PROMPT_VERSION,
    PromptContext,
    build_prompt,
    extract_sql,
    load_prompt_context,
    repair_prompt,
)
from energie_sql_bench.questions import Item, Question, build_items, load_questions
from energie_sql_bench.records import REPAIRABLE, AttemptRecord, Outcome, Usage
from energie_sql_bench.resultset import ResultSet
from energie_sql_bench.scoring import cost_usd, score_item, summarize
from energie_sql_bench.taxonomy import auto_labels

MAX_REPAIRS = 2
MAX_CONSECUTIVE_PROVIDER_ERRORS = 3
EST_CHARS_PER_TOKEN = 3.5
EST_OUTPUT_TOKENS = 500
EST_REPAIR_FACTOR = 1.5


class RunError(RuntimeError):
    """A run cannot start or continue (snapshot drift, missing price, cost estimate above the limit)."""


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    provider: str
    model: str
    variant: str
    split: str = "test"
    langs: tuple[str, ...] = ("de", "en")
    repeats: int = 1
    self_correct: bool = False
    max_usd: float = 5.0
    limit: int | None = None

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["langs"] = list(self.langs)
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> RunSpec:
        return cls(**{**data, "langs": tuple(data["langs"])})


@dataclass(frozen=True)
class BenchContext:
    questions: list[Question]
    gold: dict[str, GoldEntry]
    prompt: PromptContext


@dataclass
class RunResult:
    outcomes: list[Outcome] = field(default_factory=list)
    responses: list[dict[str, Any]] = field(default_factory=list)
    predictions: dict[str, dict[str, Any]] = field(default_factory=dict)
    complete: bool = True
    aborted_reason: str | None = None
    cost_usd: float = 0.0


@dataclass(frozen=True)
class _Evaluation:
    status: str
    sql: str | None = None
    sha: str | None = None
    guard_reason: str | None = None
    error: str | None = None
    db_ms: float = 0.0
    result: ResultSet | None = None


def load_context(settings: Settings) -> BenchContext:
    questions = load_questions(settings.path("bench/questions"))
    return BenchContext(
        questions, load_gold(settings.path("bench/gold")), load_prompt_context(settings, questions)
    )


def default_run_id(
    provider: str, model: str, variant: str, self_correct: bool, split: str, today: dt.date
) -> str:
    slug = re.sub(r"[^a-z0-9.]+", "-", model.lower()).strip("-")
    return f"{provider}-{slug}-{variant}{'-sc' if self_correct else ''}-{split}-{today:%Y%m%d}"


def select_items(ctx: BenchContext, spec: RunSpec) -> list[Item]:
    items = build_items(ctx.questions, spec.split, spec.langs)
    return items[: spec.limit] if spec.limit else items


def prompt_tokens(usage: Usage) -> int:
    """Size of the prompt as the provider counted it: fresh input plus cache writes plus cache reads."""
    return usage.input_tokens + usage.cache_creation_tokens + usage.cache_read_tokens


def prompt_token_limit(settings: Settings, provider: str) -> int | None:
    """Largest prompt a run may report. Ollama silently drops the head of a prompt that does not fit
    num_ctx, so the limit keeps room for the answer; the Anthropic limit guards the cost estimate."""
    budget = settings.prompt_budget
    if provider == "ollama":
        return settings.ollama.num_ctx - budget.output_reserve_tokens
    if provider == "anthropic":
        return budget.anthropic_max_prompt_tokens
    return None


def _evaluate(
    text: str, executor: Executor, cache: dict[str, ExecResult], predictions: dict[str, dict[str, Any]]
) -> _Evaluation:
    extraction = extract_sql(text)
    if extraction.abstained:
        return _Evaluation("abstain")
    if extraction.sql is None:
        return _Evaluation("no_sql", error=extraction.error)
    sql = extraction.sql
    sha = sql_sha256(sql)
    verdict = check_sql(sql)
    if not verdict.allowed:
        return _Evaluation("parse_error" if verdict.parse_error else "blocked", sql, sha, verdict.reason)
    if sha not in cache:
        executed = ExecResult.from_json(executor.run(sql).to_json())
        cache[sha] = executed
        predictions[sha] = executed.to_json()
    executed = cache[sha]
    if not executed.ok or executed.result is None:
        status = "timeout" if executed.error_kind == "timeout" else "db_error"
        return _Evaluation(status, sql, sha, None, executed.error, executed.db_ms)
    status = "truncated" if executed.result.truncated else "ok"
    return _Evaluation(status, sql, sha, None, None, executed.db_ms, executed.result)


def execute_run(
    spec: RunSpec,
    variant: VariantSpec,
    ctx: BenchContext,
    provider: Provider,
    executor: Executor,
    price: ModelPrice,
    compare: CompareSettings,
    items: list[Item] | None = None,
    token_limit: int | None = None,
) -> RunResult:
    items = select_items(ctx, spec) if items is None else items
    out = RunResult()
    cache: dict[str, ExecResult] = {}
    errors_in_row = 0
    max_attempts = MAX_REPAIRS + 1 if spec.self_correct else 1
    for repeat in range(spec.repeats):
        for item in items:
            prompt = build_prompt(item, variant, ctx.prompt)
            attempts: list[AttemptRecord] = []
            result: ResultSet | None = None
            item_cost = 0.0
            for attempt in range(max_attempts):
                request = Request(
                    item.item_id, spec.model, prompt.system, prompt.messages, prompt.hash, repeat, attempt
                )
                base = {
                    "attempt": attempt,
                    "item_id": item.item_id,
                    "model": spec.model,
                    "prompt_hash": prompt.hash,
                    "repeat": repeat,
                }
                try:
                    completion = provider.complete(request)
                except ProviderError as exc:
                    errors_in_row += 1
                    message = str(exc)[:500]
                    out.responses.append(
                        {
                            **base,
                            "error": message,
                            "llm_ms": 0.0,
                            "meta": {},
                            "prompt_tokens": 0,
                            "text": None,
                            "usage": Usage().to_json(),
                        }
                    )
                    attempts.append(
                        AttemptRecord(
                            attempt,
                            prompt.hash,
                            "provider_error",
                            None,
                            None,
                            None,
                            message,
                            Usage(),
                            0.0,
                            0.0,
                        )
                    )
                    result = None
                    break
                errors_in_row = 0
                tokens = prompt_tokens(completion.usage)
                out.responses.append(
                    {
                        **base,
                        "error": None,
                        "llm_ms": completion.llm_ms,
                        "meta": completion.meta,
                        "prompt_tokens": tokens,
                        "text": completion.text,
                        "usage": completion.usage.to_json(),
                    }
                )
                item_cost += cost_usd(completion.usage, price)
                if token_limit is not None and tokens > token_limit:
                    out.cost_usd += item_cost
                    out.complete = False
                    out.aborted_reason = (
                        f"Prompt mit {tokens} Tokens über der Grenze {token_limit} ({item.item_id}): "
                        "Kontext zu klein oder Schätzung falsch, Lauf ungültig"
                    )
                    return out
                ev = _evaluate(completion.text, executor, cache, out.predictions)
                result = ev.result
                attempts.append(
                    AttemptRecord(
                        attempt,
                        prompt.hash,
                        ev.status,
                        ev.sql,
                        ev.sha,
                        ev.guard_reason,
                        ev.error,
                        completion.usage,
                        completion.llm_ms,
                        ev.db_ms,
                    )
                )
                if ev.status in REPAIRABLE and attempt + 1 < max_attempts:
                    prompt = repair_prompt(prompt, completion.text, ev.guard_reason or ev.error or ev.status)
                    continue
                break
            final = attempts[-1]
            q = item.question
            correct, strict, extra, reason = score_item(q, ctx.gold.get(q.id), final.status, result, compare)
            labels = auto_labels(q.expect, final.status, final.error, correct, reason)
            out.outcomes.append(
                Outcome(
                    item.item_id,
                    q.id,
                    item.lang,
                    q.tier,
                    q.expect,
                    repeat,
                    tuple(attempts),
                    final.status,
                    correct,
                    strict,
                    extra,
                    reason,
                    labels,
                    item_cost,
                )
            )
            out.cost_usd += item_cost
            if errors_in_row >= MAX_CONSECUTIVE_PROVIDER_ERRORS:
                out.complete = False
                out.aborted_reason = f"{errors_in_row} Providerfehler in Folge"
                return out
            if out.cost_usd > spec.max_usd:
                out.complete = False
                out.aborted_reason = (
                    f"Kostenobergrenze {spec.max_usd:.2f} USD überschritten ({out.cost_usd:.4f} USD)"
                )
                return out
    return out


def estimate_cost(
    spec: RunSpec,
    variant: VariantSpec,
    ctx: BenchContext,
    price: ModelPrice,
    items: list[Item],
    chars_per_token: float = EST_CHARS_PER_TOKEN,
) -> float:
    """Upper-bound preflight estimate: no cache discount, 500 output tokens per call, 1.5x with self-correction."""
    input_tokens = sum(prompt_chars(variant, ctx, items)) / chars_per_token
    per_repeat = (input_tokens * price.input + len(items) * EST_OUTPUT_TOKENS * price.output) / 1_000_000
    factor = EST_REPAIR_FACTOR if spec.self_correct else 1.0
    return per_repeat * spec.repeats * factor


def prompt_chars(variant: VariantSpec, ctx: BenchContext, items: list[Item]) -> list[int]:
    sizes = []
    for item in items:
        prompt = build_prompt(item, variant, ctx.prompt)
        sizes.append(len(prompt.system) + sum(len(content) for _, content in prompt.messages))
    return sizes


def _check_snapshot(settings: Settings) -> str:
    from energie_sql_bench.execute import connect_mssql, fetch_all
    from energie_sql_bench.snapshot import compare_fingerprints, compute_fingerprint

    stored = read_json(settings.path("snapshot/fingerprint.json"))
    con = connect_mssql(settings.db)
    try:
        live = compute_fingerprint(partial(fetch_all, con), settings.snapshot)
    finally:
        con.close()
    diffs = compare_fingerprints(stored, live)
    if diffs:
        raise RunError(f"Snapshot weicht ab ({len(diffs)} Abweichungen): esb snapshot --check")
    return stored["digest"]


def _validate(settings: Settings, spec: RunSpec) -> tuple[VariantSpec, ModelPrice]:
    if spec.variant not in settings.variants:
        raise RunError(f"unbekannte Variante {spec.variant}")
    if spec.model not in settings.pricing:
        raise RunError(f"kein Preis für {spec.model} in pricing.toml")
    if settings.path(f"results/runs/{spec.run_id}").exists():
        raise RunError(f"Lauf {spec.run_id} existiert bereits")
    return settings.variants[spec.variant], settings.pricing[spec.model]


def _check_prompt_fits(
    settings: Settings, spec: RunSpec, variant: VariantSpec, ctx: BenchContext, items: list[Item]
) -> None:
    """Refuse a run whose longest prompt, by the character estimate, cannot fit the token limit."""
    limit = prompt_token_limit(settings, spec.provider)
    if limit is None or not items:
        return
    estimated = max(prompt_chars(variant, ctx, items)) / settings.prompt_budget.chars_per_token
    if estimated > limit:
        raise RunError(f"geschätzter Prompt {estimated:.0f} Tokens über der Grenze {limit} ({spec.provider})")


def preflight_estimate(settings: Settings, spec: RunSpec) -> float:
    variant, price = _validate(settings, spec)
    ctx = load_context(settings)
    return estimate_cost(
        spec, variant, ctx, price, select_items(ctx, spec), settings.prompt_budget.chars_per_token
    )


def run_config(
    spec: RunSpec,
    variant: VariantSpec,
    settings: Settings,
    provider_meta: dict[str, Any],
    price: ModelPrice,
    digest: str,
) -> dict[str, Any]:
    return {
        "compare": asdict(settings.compare),
        "created": dt.date.today().isoformat(),
        "esb_version": __version__,
        "eur_usd": settings.cost.eur_usd,
        "price": asdict(price),
        "prompt_token_limit": prompt_token_limit(settings, spec.provider),
        "prompt_version": PROMPT_VERSION,
        "provider": provider_meta,
        "rate_date": settings.cost.rate_date,
        "run_id": spec.run_id,
        "snapshot": digest,
        "spec": spec.to_json(),
        "synthetic": spec.provider == "synthetic",
        "variant": asdict(variant),
    }


def live_run(settings: Settings, spec: RunSpec) -> tuple[Path, dict[str, Any]]:
    from energie_sql_bench.execute import MssqlExecutor
    from energie_sql_bench.llm import make_provider
    from energie_sql_bench.llm.recorder import write_run

    variant, price = _validate(settings, spec)
    ctx = load_context(settings)
    items = select_items(ctx, spec)
    estimate = estimate_cost(spec, variant, ctx, price, items, settings.prompt_budget.chars_per_token)
    if estimate > spec.max_usd:
        raise RunError(f"Kostenschätzung {estimate:.2f} USD liegt über --max-usd {spec.max_usd:.2f}")
    _check_prompt_fits(settings, spec, variant, ctx, items)
    provider = make_provider(spec.provider, spec.model, settings, ctx.questions)  # fails fast without a key
    digest = _check_snapshot(settings)
    executor = MssqlExecutor(settings.db)
    try:
        result = execute_run(
            spec,
            variant,
            ctx,
            provider,
            executor,
            price,
            settings.compare,
            items,
            prompt_token_limit(settings, spec.provider),
        )
    finally:
        executor.close()
    summary = summarize(
        result.outcomes, spec.repeats, settings.cost.eur_usd, result.complete, result.aborted_reason
    )
    run_dir = settings.path(f"results/runs/{spec.run_id}")
    write_run(
        run_dir,
        run_config(spec, variant, settings, provider.describe(), price, digest),
        result.responses,
        result.predictions,
        summary,
    )
    return run_dir, summary


def replay_run(settings: Settings, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(recomputed summary, stored summary) of a committed run, without network or database."""
    from energie_sql_bench.llm.recorder import read_run
    from energie_sql_bench.llm.replay import RecordedExecutor, ReplayProvider

    files = read_run(settings.path(f"results/runs/{run_id}"))
    cfg = files.config
    spec = RunSpec.from_json(cfg["spec"])
    ctx = load_context(settings)
    result = execute_run(
        spec,
        VariantSpec(**cfg["variant"]),
        ctx,
        ReplayProvider(files.responses),
        RecordedExecutor(files.predictions),
        ModelPrice(**cfg["price"]),
        CompareSettings(**cfg["compare"]),
        token_limit=cfg.get("prompt_token_limit"),
    )
    summary = summarize(
        result.outcomes, spec.repeats, float(cfg["eur_usd"]), result.complete, result.aborted_reason
    )
    return summary, files.summary


def summaries_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return dump_json(a) == dump_json(b)


def list_runs(settings: Settings) -> list[str]:
    runs_dir = settings.path("results/runs")
    if not runs_dir.is_dir():
        return []
    return sorted(p.name for p in runs_dir.iterdir() if (p / "config.json").is_file())
