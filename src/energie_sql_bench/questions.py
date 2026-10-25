"""Question items (bench/questions/qNNN.yaml): validation, splits, items, tables, n-gram overlap."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import sqlglot
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlglot import exp

from energie_sql_bench.config import CompareSettings

_TOKEN = re.compile(r"[a-zäöüß0-9]+")


class Tolerance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rel: float = 1e-4
    abs: float = 0.005


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^q\d{3}$")
    split: Literal["dev", "test"]
    tier: Literal["T1", "T2", "T3", "T4", "A"]
    tags: list[str] = Field(default_factory=list)
    de: str
    en: str
    as_of: str = "2026-10-01"
    expect: Literal["rows", "abstain"]
    ordered: bool = False
    tolerance: Tolerance | None = None
    gold_sql: str | None = None
    check_sql: str | None = None
    tables: list[str] = Field(default_factory=list)
    duckdb: str = "ok"
    notes: str

    @model_validator(mode="after")
    def _consistent(self) -> Question:
        if not self.de.strip() or not self.en.strip():
            raise ValueError("de und en müssen gesetzt sein")
        if self.de.strip() == self.en.strip():
            raise ValueError("de und en dürfen nicht gleich sein")
        if self.expect == "abstain":
            if self.tier != "A":
                raise ValueError("Enthaltungsfragen haben tier A")
            if self.gold_sql or self.check_sql or self.tables:
                raise ValueError("Enthaltungsfragen haben kein SQL und keine Tabellen")
        else:
            if self.tier == "A":
                raise ValueError("tier A nur mit expect: abstain")
            if not self.gold_sql or not self.check_sql:
                raise ValueError("gold_sql und check_sql sind Pflicht")
        if self.duckdb != "ok" and not (self.duckdb.startswith("skip: ") and len(self.duckdb.strip()) > 6):
            raise ValueError("duckdb muss 'ok' oder 'skip: <Grund>' sein")
        return self

    @property
    def duckdb_ok(self) -> bool:
        return self.duckdb == "ok"

    def text(self, lang: str) -> str:
        if lang == "de":
            return self.de
        if lang == "en":
            return self.en
        raise ValueError(f"Sprache {lang} nicht unterstützt")


@dataclass(frozen=True)
class Item:
    question: Question
    lang: str

    @property
    def item_id(self) -> str:
        return f"{self.question.id}-{self.lang}"

    @property
    def text(self) -> str:
        return self.question.text(self.lang)


def load_questions(directory: Path) -> list[Question]:
    questions: list[Question] = []
    for path in sorted(directory.glob("q*.yaml")):
        question = Question.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        if question.id != path.stem:
            raise ValueError(f"{path.name}: id {question.id} passt nicht zum Dateinamen")
        questions.append(question)
    return questions


def build_items(questions: Iterable[Question], split: str, langs: Iterable[str]) -> list[Item]:
    langs = tuple(langs)
    return [Item(q, lang) for q in questions if split in ("all", q.split) for lang in langs]


def tables_in_sql(sql: str) -> list[str]:
    tree = sqlglot.parse_one(sql, read="tsql")
    ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    found: set[str] = set()
    for table in tree.find_all(exp.Table):
        name, schema = str(table.name).lower(), str(table.db).lower()
        if not schema and name in ctes:
            continue
        found.add(f"{schema}.{name}" if schema else name)
    return sorted(found)


def tolerance_for(question: Question, compare: CompareSettings) -> tuple[float, float]:
    if question.tolerance is not None:
        return question.tolerance.rel, question.tolerance.abs
    return compare.rel_tol, compare.abs_tol


def ngram_jaccard(a: str, b: str, n: int = 3) -> float:
    def grams(text: str) -> set[tuple[str, ...]]:
        tokens = _TOKEN.findall(text.lower())
        return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}

    ga, gb = grams(a), grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def load_fewshot(path: Path, questions: list[Question]) -> list[Question]:
    ids = yaml.safe_load(path.read_text(encoding="utf-8"))["examples"]
    by_id = {q.id: q for q in questions}
    return [by_id[qid] for qid in ids]
