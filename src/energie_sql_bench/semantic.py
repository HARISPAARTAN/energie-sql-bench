"""Semantic layer (semantic/measures.yaml): measures, synonyms and rules rendered for the prompt."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class Measure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    name_de: str
    name_en: str
    unit: str
    description: str
    sql: str


class SemanticLayer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_commit: str
    rules: list[str]
    synonyms: dict[str, str]
    measures: list[Measure]


def load_semantic(path: Path) -> SemanticLayer:
    return SemanticLayer.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _one_line(text: str) -> str:
    return " ".join(text.split())


def render_semantic(layer: SemanticLayer) -> str:
    lines = ["Rules:"]
    lines += [f"- {_one_line(rule)}" for rule in layer.rules]
    lines += ["", "Synonyms (term in a question -> term in the warehouse):"]
    lines += [f"- {term} -> {target}" for term, target in sorted(layer.synonyms.items())]
    lines += ["", "Measures (name DE / EN [unit]: T-SQL template; placeholders in braces):"]
    for m in layer.measures:
        lines.append(
            f"- {m.name_de} / {m.name_en} [{m.unit}]: {_one_line(m.description)} SQL: {_one_line(m.sql)}"
        )
    return "\n".join(lines) + "\n"
