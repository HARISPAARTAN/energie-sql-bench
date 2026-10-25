"""Character ceilings per prompt variant (review finding I2): a prompt that grows past its ceiling must be a
conscious decision, because the local model silently drops the head of a prompt longer than its context."""

from pathlib import Path

import pytest

from energie_sql_bench.config import load_settings
from energie_sql_bench.prompts import build_prompt, load_prompt_context
from energie_sql_bench.questions import build_items, load_questions

REPO = Path(__file__).resolve().parents[2]
SETTINGS = load_settings(REPO, environ={})
QUESTIONS = load_questions(REPO / "bench" / "questions")
CTX = load_prompt_context(SETTINGS, QUESTIONS)
ITEMS = build_items(QUESTIONS, "all", ("de", "en"))

# Measured maximum over all 140 items, rounded up to the next 500 characters (system prompt plus messages).
# Abstention items of v5 and v6 receive the full schema, which is why their ceiling equals the full-schema ceiling.
CEILING_CHARS = {"v1": 14_500, "v2": 18_500, "v3": 25_000, "v4": 29_000, "v5": 29_000, "v6": 29_000}
WORST_CASE_CHARS_PER_TOKEN = 2.5  # far below the roughly 3.3 to 4 of German, SQL and identifiers


def prompt_chars(variant_id: str) -> list[int]:
    variant = SETTINGS.variants[variant_id]
    sizes = []
    for item in ITEMS:
        prompt = build_prompt(item, variant, CTX)
        sizes.append(len(prompt.system) + sum(len(content) for _, content in prompt.messages))
    return sizes


def test_every_variant_has_a_ceiling() -> None:
    assert set(CEILING_CHARS) == set(SETTINGS.variants)


@pytest.mark.parametrize("variant_id", sorted(CEILING_CHARS))
def test_prompt_stays_under_its_ceiling(variant_id: str) -> None:
    assert max(prompt_chars(variant_id)) <= CEILING_CHARS[variant_id]


@pytest.mark.parametrize("variant_id", sorted(CEILING_CHARS))
def test_ceiling_fits_the_local_context_even_in_the_worst_case(variant_id: str) -> None:
    budget = SETTINGS.prompt_budget
    estimated = CEILING_CHARS[variant_id] / budget.chars_per_token + budget.output_reserve_tokens
    worst = CEILING_CHARS[variant_id] / WORST_CASE_CHARS_PER_TOKEN + budget.output_reserve_tokens
    assert estimated < SETTINGS.ollama.num_ctx
    assert worst < SETTINGS.ollama.num_ctx


def test_local_context_is_16384() -> None:
    assert SETTINGS.ollama.num_ctx == 16384
