"""Scoring: item verdicts, intervals, exact McNemar tests, percentiles, cost and the run summary.

Repeats and statistics (review findings I1 and I4). The German and the English item of one intent are paired
(same question, same gold result), and the repeats of one item share prompt and model, so neither may be counted as
independent observations:

* Accuracy is aggregated per item first (mean correctness over the repeats of that item).
* The accuracy interval is a question-level percentile bootstrap for every repeat count (95 %, fixed seed,
  BOOTSTRAP_RESAMPLES resamples): intents are drawn with replacement, each carrying its German and English items
  and their per-item means. The intent is the unit because its two language items and all its repeats are related;
  the effective sample size is the number of intents (60 in the test split), not the number of items (120).
  A bootstrap interval collapses to a point when every intent has the same outcome; read it together with n.
* The paired McNemar tests (between configurations in the report) run on intents: an item counts as correct when
  strictly more than half of its repeats are correct (a tie is not correct), and an intent counts as correct for a
  configuration when all its language items are correct by that rule. The pairs are intents, never items and never
  (item, repeat). The German against English comparison inside a run pairs the two language items of each intent.
* The pooled counts "correct" and "n" of a block are descriptive totals over all repeats; they carry no interval.

METHODOLOGY_NOTE is the wording the report and docs/methodology.md reuse."""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Iterable
from fractions import Fraction
from typing import Any

from energie_sql_bench.compare import compare, is_empty_result
from energie_sql_bench.config import CompareSettings, ModelPrice
from energie_sql_bench.gold import GoldEntry
from energie_sql_bench.questions import Question, tolerance_for
from energie_sql_bench.records import Outcome, Usage
from energie_sql_bench.resultset import ResultSet

SUMMARY_VERSION = 3
BOOTSTRAP_SEED = 20261025
BOOTSTRAP_RESAMPLES = 2000
METHODOLOGY_NOTE = {
    "de": (
        "Das deutsche und das englische Item eines Intents sind gepaart, Wiederholungen desselben Items sind "
        "nicht unabhängig. Die Genauigkeit wird zuerst je Item über die Wiederholungen gemittelt. Das "
        "95 %-Intervall ist bei jeder Wiederholungszahl ein Bootstrap-Intervall über die Intents (feste Saat); die "
        "wirksame Stichprobengröße ist die Zahl der Intents (60), nicht die der Items (120). McNemar-Tests laufen "
        "auf Intents: Ein Item gilt als richtig, wenn mehr als die Hälfte seiner Wiederholungen richtig ist, ein "
        "Intent, wenn alle seine Sprachitems richtig sind."
    ),
    "en": (
        "The German and the English item of one intent are paired, and repeats of the same item are not "
        "independent. Accuracy is first averaged per item over its repeats. The 95 % interval is, for every "
        "number of repeats, a bootstrap interval over intents (fixed seed); the effective sample size is the "
        "number of intents (60), not the number of items (120). McNemar tests run on intents: an item counts as "
        "correct when more than half of its repeats are correct, an intent when all its language items are "
        "correct."
    ),
}


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


def majority_by_item(pairs: Iterable[tuple[str, bool]]) -> dict[str, bool]:
    """Per-item majority outcome from (item_id, correct) pairs: True when strictly more than half are correct."""
    counts: dict[str, list[int]] = {}
    for item_id, correct in pairs:
        entry = counts.setdefault(item_id, [0, 0])
        entry[0] += bool(correct)
        entry[1] += 1
    return {item_id: 2 * hits > total for item_id, (hits, total) in sorted(counts.items())}


def majority_by_question(rows: Iterable[tuple[str, str, bool]]) -> dict[str, bool]:
    """Per-intent outcome from (question_id, item_id, correct) rows: every language item must be correct by majority.

    The German and English item of an intent are paired, so the intent, not the item, is the unit of a paired test.
    """
    rows = list(rows)
    by_item = majority_by_item((item_id, correct) for _, item_id, correct in rows)
    question_of = {item_id: question_id for question_id, item_id, _ in rows}
    outcome: dict[str, bool] = {}
    for item_id, correct in by_item.items():
        question_id = question_of[item_id]
        outcome[question_id] = outcome.get(question_id, True) and correct
    return dict(sorted(outcome.items()))


def paired_discordant(a: dict[str, bool], b: dict[str, bool]) -> tuple[int, int, int]:
    """(common keys, only a correct, only b correct) for two majority maps (per item or per intent); feed the last two to mcnemar_exact."""
    keys = sorted(set(a) & set(b))
    return len(keys), sum(1 for k in keys if a[k] and not b[k]), sum(1 for k in keys if b[k] and not a[k])


def bootstrap_interval(
    clusters: list[tuple[float, int]],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float]:
    """95 % percentile bootstrap of the item-weighted accuracy; clusters are (sum of item means, item count)."""
    if not clusters:
        return 0.0, 1.0
    rng = random.Random(seed)
    size = len(clusters)
    stats = []
    for _ in range(resamples):
        total = weight = 0
        for _ in range(size):
            s, w = clusters[rng.randrange(size)]
            total += s
            weight += w
        stats.append(total / weight)
    return percentile(stats, 2.5) or 0.0, percentile(stats, 97.5) or 0.0


def _item_means(outcomes: list[Outcome], attr: str) -> dict[str, tuple[str, float]]:
    """item_id -> (question_id, mean of attr over the repeats of that item)."""
    grouped: dict[str, list[Outcome]] = {}
    for o in outcomes:
        grouped.setdefault(o.item_id, []).append(o)
    return {
        item_id: (rows[0].question_id, sum(bool(getattr(o, attr)) for o in rows) / len(rows))
        for item_id, rows in sorted(grouped.items())
    }


def _block(outcomes: list[Outcome], repeats: int, attr: str) -> dict[str, Any]:
    per_repeat = []
    for r in range(repeats):
        sub = [o for o in outcomes if o.repeat == r]
        per_repeat.append(r6(sum(getattr(o, attr) for o in sub) / len(sub)) if sub else 0.0)
    k = sum(getattr(o, attr) for o in outcomes)
    means = _item_means(outcomes, attr)
    by_question: dict[str, list[float]] = {}
    for question_id, mean in means.values():
        by_question.setdefault(question_id, []).append(mean)
    lo, hi = bootstrap_interval([(sum(v), len(v)) for _, v in sorted(by_question.items())])
    return {
        "ci95": [r6(lo), r6(hi)],
        "correct": k,
        "interval": "bootstrap",
        "questions": len(by_question),
        "items": len(means),
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
    majority = majority_by_item((o.item_id, o.correct) for o in outcomes)
    langs = {o.item_id: (o.question_id, o.lang) for o in outcomes}
    pairs: dict[str, dict[str, bool]] = {}
    for item_id, correct in majority.items():
        question_id, lang = langs[item_id]
        pairs.setdefault(question_id, {})[lang] = correct
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
        "n_items": len({o.item_id for o in outcomes}),
        "repair_attempts": sum(1 for a in attempts if a.attempt > 0),
        "repaired_correct": sum(1 for o in outcomes if o.correct and len(o.attempts) > 1),
        "prompt_tokens_max": max(
            (
                a.usage.input_tokens + a.usage.cache_creation_tokens + a.usage.cache_read_tokens
                for a in attempts
            ),
            default=0,
        ),
        "repeats": repeats,
        "summary_version": SUMMARY_VERSION,
        "tokens": usage.to_json(),
        "validity": {"n": len(rows), "rate": r6(valid / len(rows)) if rows else 0.0, "valid": valid},
    }
