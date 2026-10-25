"""Deterministic prompt assembly per variant (v1..v6), prompt hash and SQL extraction."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import Any

from energie_sql_bench.config import Settings, SnapshotSettings, VariantSpec
from energie_sql_bench.files import read_json, read_yaml
from energie_sql_bench.questions import Item, Question, load_fewshot
from energie_sql_bench.schema import render_schema, retrieve_tables
from energie_sql_bench.semantic import SemanticLayer, load_semantic, render_semantic

PROMPT_VERSION = "1"
ABSTAIN_TOKEN = "NICHT_BEANTWORTBAR"
RULES = (
    "You translate a question about the German electricity market into one Microsoft SQL Server (T-SQL) query.\n"
    "Rules:\n"
    "1. Reply with exactly one fenced code block ```sql ... ``` that contains one read-only SELECT statement "
    "(WITH ... SELECT is allowed). Put nothing else in code blocks.\n"
    "2. Use only the tables and views listed below, always with their schema prefix (dw. or rpt.).\n"
    "3. Use T-SQL syntax: TOP instead of LIMIT; DATEADD, DATEDIFF, DATETRUNC; "
    "AT TIME ZONE 'W. Europe Standard Time' for German local time.\n"
    "4. Return exactly the columns the question asks for, in the order and unit it names. Do not round.\n"
    f"5. If the warehouse cannot answer the question, reply only with {ABSTAIN_TOKEN} and no SQL.\n"
)
QUESTION_LABEL = {"de": "Frage", "en": "Question"}
_FENCE = re.compile(r"```[ \t]*(?:sql|tsql|t-sql)?[ \t]*\r?\n(.*?)```", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class PromptContext:
    schema: dict[str, Any]
    descriptions: dict[str, Any]
    semantic: SemanticLayer
    fewshot: tuple[Question, ...]
    snapshot: SnapshotSettings


@dataclass(frozen=True)
class Prompt:
    variant: str
    system: str
    messages: tuple[tuple[str, str], ...]

    @property
    def hash(self) -> str:
        payload = json.dumps(
            {
                "messages": [list(m) for m in self.messages],
                "system": self.system,
                "variant": self.variant,
                "version": PROMPT_VERSION,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Extraction:
    sql: str | None
    abstained: bool
    error: str | None


def load_prompt_context(settings: Settings, questions: list[Question]) -> PromptContext:
    return PromptContext(
        schema=read_json(settings.path("schema/schema.json")),
        descriptions=read_yaml(settings.path("schema/descriptions.yaml")),
        semantic=load_semantic(settings.path("semantic/measures.yaml")),
        fewshot=tuple(load_fewshot(settings.path("bench/fewshot/fewshot.yaml"), questions)),
        snapshot=settings.snapshot,
    )


def data_cut_line(s: SnapshotSettings) -> str:
    return (
        f"Data cut: SMARD time series from {s.smard_start} to {s.smard_end} (local dates), installed capacity "
        f"by month up to {s.mastr_end}, as of {s.as_of}. Only the bidding zone DE-LU has facts."
    )


def select_tables(item: Item, variant: VariantSpec, ctx: PromptContext) -> list[str] | None:
    """Tables for the schema context; None means the full schema."""
    if variant.schema == "full":
        return None
    if variant.schema == "oracle":
        return sorted(item.question.tables) or None
    if variant.schema == "retrieved":
        return retrieve_tables(item.text, ctx.schema, ctx.descriptions, ctx.semantic.synonyms)
    raise ValueError(f"unbekannte Schema-Variante {variant.schema}")


def render_fewshot(examples: tuple[Question, ...]) -> str:
    blocks = []
    for n, q in enumerate(examples, start=1):
        answer = f"```sql\n{(q.gold_sql or '').strip()}\n```" if q.expect == "rows" else ABSTAIN_TOKEN
        blocks.append(f"Example {n}\nFrage: {q.de}\nQuestion: {q.en}\nAnswer:\n{answer}")
    return "\n\n".join(blocks)


def build_system(variant: VariantSpec, ctx: PromptContext, tables: list[str] | None) -> str:
    parts = [
        RULES.rstrip(),
        data_cut_line(ctx.snapshot),
        "",
        "## Schema",
        render_schema(ctx.schema, ctx.descriptions, tables).rstrip(),
    ]
    if variant.semantic:
        parts += ["", "## Semantic layer", render_semantic(ctx.semantic).rstrip()]
    if variant.fewshot:
        parts += ["", "## Examples", render_fewshot(ctx.fewshot)]
    return "\n".join(parts).rstrip() + "\n"


def build_prompt(item: Item, variant: VariantSpec, ctx: PromptContext) -> Prompt:
    system = build_system(variant, ctx, select_tables(item, variant, ctx))
    return Prompt(variant.id, system, (("user", f"{QUESTION_LABEL[item.lang]}: {item.text}"),))


def repair_prompt(prompt: Prompt, assistant_text: str, feedback: str) -> Prompt:
    note = (
        "The query could not be used: "
        + feedback.strip()[:1000]
        + f"\nReply with a corrected query in exactly one ```sql block, or with {ABSTAIN_TOKEN}."
    )
    return replace(prompt, messages=prompt.messages + (("assistant", assistant_text), ("user", note)))


def extract_sql(text: str | None) -> Extraction:
    blocks = [b.strip() for b in _FENCE.findall(text or "")]
    blocks = [b for b in blocks if b]
    if len(blocks) == 1:
        return Extraction(blocks[0], False, None)
    if len(blocks) > 1:
        return Extraction(None, False, "mehrere SQL-Blöcke")
    if ABSTAIN_TOKEN in (text or ""):
        return Extraction(None, True, None)
    return Extraction(None, False, "kein SQL-Block")
