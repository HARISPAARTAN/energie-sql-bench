"""Scoring: item verdicts, Wilson intervals, exact McNemar tests, percentiles, cost and the run summary."""

from __future__ import annotations

import math
from collections import Counter
from fractions import Fraction
from typing import Any

from energie_sql_bench.compare import compare, is_empty_result
from energie_sql_bench.config import CompareSettings, ModelPrice
from energie_sql_bench.gold import GoldEntry
from energie_sql_bench.questions import Question, tolerance_for
from energie_sql_bench.records import Outcome, Usage
from energie_sql_bench.resultset import ResultSet

SUMMARY_VERSION = 1


def r6(x: float) -> float:
    return round(float(x), 6)


def score_item(
    question: Question,
    gold: GoldEntry | None,
    status: str,
    result: ResultSet | None,
    compare_settings: CompareSettings,
) -> tuple[bool, bool, int, str]:
    """(correct, strict, extra_columns, reason) for the final attempt of one item."""
    if question.expect == "abstain":
        if status == "abstain":
            return True, True, 0, "Enthaltung"
        if status == "ok" and is_empty_result(result):
            return True, True, 0, "leeres Ergebnis"
        if status in ("ok", "truncated"):
            return False, False, 0, "beantwortet statt enthalten"
        return False, False, 0, f"Status {status}"
    if status == "abstain":
        return False, False, 0, "Enthaltung statt Antwort"
    if status not in ("ok", "truncated") or result is None or gold is None or gold.result is None:
        return False, False, 0, f"Status {status}"
    rel, abs_ = tolerance_for(question, compare_settings)
    verdict = compare(gold.result, result, question.ordered, rel, abs_)
    return verdict.match, verdict.strict, verdict.extra_columns, verdict.reason


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar test on the discordant pairs b and c."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(Fraction(math.comb(n, k), 2**n) for k in range(min(b, c) + 1))
    return float(min(Fraction(1), 2 * tail))


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


def cost_usd(usage: Usage, price: ModelPrice) -> float:
    return (
        usage.input_tokens * price.input
        + usage.cache_creation_tokens * price.cache_write
        + usage.cache_read_tokens * price.cache_read
        + usage.output_tokens * price.output
    ) / 1_000_000


def _block(outcomes: list[Outcome], repeats: int, attr: str) -> dict[str, Any]:
    per_repeat = []
    for r in range(repeats):
        sub = [o for o in outcomes if o.repeat == r]
        per_repeat.append(r6(sum(getattr(o, attr) for o in sub) / len(sub)) if sub else 0.0)
    k = sum(getattr(o, attr) for o in outcomes)
    lo, hi = wilson(k, len(outcomes))
    return {
        "ci95": [r6(lo), r6(hi)],
        "correct": k,
        "max": max(per_repeat, default=0.0),
        "mean": r6(sum(per_repeat) / len(per_repeat)) if per_repeat else 0.0,
        "min": min(per_repeat, default=0.0),
        "n": len(outcomes),
        "per_repeat": per_repeat,
    }


def _group(outcomes: list[Outcome], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[Outcome]] = {}
    for o in outcomes:
        groups.setdefault(getattr(o, key), []).append(o)
    return {
        name: {
            "correct": sum(o.correct for o in items),
            "ex": r6(sum(o.correct for o in items) / len(items)),
            "n": len(items),
        }
        for name, items in sorted(groups.items())
    }


def _opt(x: float | None) -> float | None:
    return None if x is None else r6(x)


def summarize(
    outcomes: list[Outcome],
    repeats: int,
    eur_usd: float,
    complete: bool = True,
    aborted_reason: str | None = None,
) -> dict[str, Any]:
    attempts = [a for o in outcomes for a in o.attempts]
    rows = [o for o in outcomes if o.expect == "rows"]
    abstain_expected = [o for o in outcomes if o.expect == "abstain"]
    predicted_abstain = [
        o for o in outcomes if o.final_status == "abstain" or (o.expect == "abstain" and o.correct)
    ]
    correct_abstain = [o for o in abstain_expected if o.correct]
    usage = sum((a.usage for a in attempts), Usage())
    usd = sum(o.cost_usd for o in outcomes)
    n_correct = sum(o.correct for o in outcomes)
    pairs: dict[tuple[str, int], dict[str, bool]] = {}
    for o in outcomes:
        pairs.setdefault((o.question_id, o.repeat), {})[o.lang] = o.correct
    de_only = sum(1 for p in pairs.values() if p.get("de") and p.get("en") is False)
    en_only = sum(1 for p in pairs.values() if p.get("en") and p.get("de") is False)
    labels = Counter(label for o in outcomes for label in o.labels)
    executed = [a.db_ms for a in attempts if a.status in ("ok", "truncated", "db_error", "timeout")]
    valid = sum(1 for o in rows if o.final_status in ("ok", "truncated"))
    return {
        "aborted_reason": aborted_reason,
        "abstention": {
            "correct": len(correct_abstain),
            "expected": len(abstain_expected),
            "precision": _opt(len(correct_abstain) / len(predicted_abstain)) if predicted_abstain else None,
            "predicted": len(predicted_abstain),
            "recall": _opt(len(correct_abstain) / len(abstain_expected)) if abstain_expected else None,
        },
        "blocked_attempts": sum(1 for a in attempts if a.status in ("blocked", "parse_error")),
        "by_lang": _group(outcomes, "lang"),
        "by_tier": _group(outcomes, "tier"),
        "complete": complete,
        "cost": {
            "eur": r6(usd / eur_usd) if eur_usd else None,
            "usd": r6(usd),
            "usd_per_correct": r6(usd / n_correct) if n_correct else None,
        },
        "de_vs_en": {"de_only": de_only, "en_only": en_only, "p_value": r6(mcnemar_exact(de_only, en_only))},
        "ex": _block(outcomes, repeats, "correct"),
        "ex_strict": _block(outcomes, repeats, "strict"),
        "items": [o.to_json() for o in outcomes],
        "labels": dict(sorted(labels.items())),
        "latency_ms": {
            "db_p50": _opt(percentile(executed, 50)),
            "db_p95": _opt(percentile(executed, 95)),
            "llm_p50": _opt(percentile([a.llm_ms for a in attempts], 50)),
            "llm_p95": _opt(percentile([a.llm_ms for a in attempts], 95)),
        },
        "n_items": len(outcomes) // repeats if repeats else len(outcomes),
        "repair_attempts": sum(1 for a in attempts if a.attempt > 0),
        "repaired_correct": sum(1 for o in outcomes if o.correct and len(o.attempts) > 1),
        "repeats": repeats,
        "summary_version": SUMMARY_VERSION,
        "tokens": usage.to_json(),
        "validity": {"n": len(rows), "rate": r6(valid / len(rows)) if rows else 0.0, "valid": valid},
    }
