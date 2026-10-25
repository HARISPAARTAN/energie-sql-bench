"""Cost plan of the planned Claude sweep, computed with the code's own estimator (no network, no database).

    uv run python tools/cost_plan.py

Upper bound: runner.estimate_cost, the preflight figure of `esb run` (whole prompt at the plain input price, no
cache discount, 500 output tokens per call). Cached expectation: the static system prefix is billed as one cache
write and then as cache reads, the question text at the input price, plus the same 500 output tokens. Neither
figure includes adaptive-thinking tokens (they bill as output) or additional cache writes after a 5-minute gap.
"""

from __future__ import annotations

from energie_sql_bench.config import load_settings
from energie_sql_bench.prompts import build_prompt
from energie_sql_bench.runner import (
    EST_OUTPUT_TOKENS,
    EST_REPAIR_FACTOR,
    RunSpec,
    _validate,
    estimate_cost,
    load_context,
    select_items,
)

CLAUDE_REPEATS = 3


def main() -> None:
    settings = load_settings()
    ctx = load_context(settings)
    per = settings.prompt_budget.chars_per_token
    print(
        f"Annahmen: {CLAUDE_REPEATS} Wiederholungen je Claude-Konfiguration, Testsplit, {per} Zeichen je Token,"
    )
    print(f"{EST_OUTPUT_TOKENS} Ausgabetoken je Aufruf, Selbstkorrektur x{EST_REPAIR_FACTOR}\n")
    print("Variante  Items  Prompt-Token (Mittel)  davon Systempräfix  Frage")
    for variant_id, variant in settings.variants.items():
        spec = RunSpec("plan", "anthropic", "claude-haiku-5-5", variant_id)
        items = select_items(ctx, spec)
        prompts = [build_prompt(item, variant, ctx.prompt) for item in items]
        system = sum(len(p.system) for p in prompts) / len(prompts) / per
        question = sum(sum(len(c) for _, c in p.messages) for p in prompts) / len(prompts) / per
        print(
            f"{variant_id:<9} {len(items):>5}  {system + question:>21.0f}  {system:>18.0f}  {question:>5.0f}"
        )
    print("\nKonfiguration                                   obere Grenze USD   mit Cache USD")
    totals: dict[str, list[float]] = {}
    for plan in settings.report.planned:
        if plan.provider != "anthropic":
            continue
        spec = RunSpec(
            "plan",
            plan.provider,
            plan.model,
            plan.variant,
            repeats=CLAUDE_REPEATS,
            self_correct=plan.self_correct,
        )
        variant, price = _validate(settings, spec)
        items = select_items(ctx, spec)
        upper = estimate_cost(spec, variant, ctx, price, items, per)
        seen: set[str] = set()
        cached = 0.0
        for _ in range(spec.repeats):
            for item in items:
                prompt = build_prompt(item, variant, ctx.prompt)
                system_tokens = len(prompt.system) / per
                question_tokens = sum(len(c) for _, c in prompt.messages) / per
                cached += system_tokens * (price.cache_read if prompt.system in seen else price.cache_write)
                seen.add(prompt.system)
                cached += question_tokens * price.input + EST_OUTPUT_TOKENS * price.output
        cached = cached / 1_000_000 * (EST_REPAIR_FACTOR if plan.self_correct else 1.0)
        print(f"{plan.key:<47} {upper:>16.2f} {cached:>15.2f}")
        total = totals.setdefault(plan.model, [0.0, 0.0])
        total[0] += upper
        total[1] += cached
    print()
    for model, (upper, cached) in totals.items():
        print(f"{model:<47} {upper:>16.2f} {cached:>15.2f}")
    print(
        f"{'Summe':<47} {sum(t[0] for t in totals.values()):>16.2f} {sum(t[1] for t in totals.values()):>15.2f}"
    )


if __name__ == "__main__":
    main()
