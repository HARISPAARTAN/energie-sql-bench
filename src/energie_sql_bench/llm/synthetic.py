"""Synthetic pipeline-test provider: no language model. It answers from the gold SQL with deterministic,
labelled faults so that guard, executor, comparator, self-correction, scoring and replay are exercised end to end.

behaviour(item_id) = sha256(item_id) mod 10:
  0-5 gold SQL; 6 gold SQL plus "LIMIT 10" (dialect error); 7 hallucinated column; 8 DELETE (blocked);
  9 wrong abstention. Repairs (attempt > 0) answer with the gold SQL. Abstention items: 0 answers with a count
  over dw.dim_region (wrong), everything else abstains (right)."""

from __future__ import annotations

import hashlib
from typing import Any

from energie_sql_bench.llm.base import Completion, Request
from energie_sql_bench.prompts import ABSTAIN_TOKEN
from energie_sql_bench.questions import Question
from energie_sql_bench.records import Usage

SYNTHETIC_MODEL = "synthetic-gold-v1"


def behaviour(item_id: str) -> int:
    return int(hashlib.sha256(item_id.encode("utf-8")).hexdigest()[:8], 16) % 10


def _fence(sql: str) -> str:
    return f"```sql\n{sql.strip()}\n```"


class SyntheticProvider:
    def __init__(self, questions: list[Question]) -> None:
        self._questions = {q.id: q for q in questions}

    def describe(self) -> dict[str, Any]:
        return {
            "model": SYNTHETIC_MODEL,
            "note": "Pipeline-Test ohne Sprachmodell: Antworten aus Gold-SQL mit festen, markierten Fehlern",
            "provider": "synthetic",
        }

    def complete(self, request: Request) -> Completion:
        question = self._questions[request.item_id.split("-")[0]]
        h = behaviour(request.item_id)
        if question.expect == "abstain":
            text = _fence("SELECT COUNT(*) AS anzahl FROM dw.dim_region") if h == 0 else ABSTAIN_TOKEN
        elif request.attempt > 0 or h <= 5:
            text = _fence(question.gold_sql or "")
        elif h == 6:
            text = _fence((question.gold_sql or "").rstrip() + "\nLIMIT 10")
        elif h == 7:
            text = _fence("SELECT SUM(erzeugung_gwh) AS wert FROM dw.fact_erzeugung")
        elif h == 8:
            text = _fence("DELETE FROM dw.fact_preis WHERE 1 = 0")
        else:
            text = ABSTAIN_TOKEN
        return Completion(text, Usage(), 0.0, {"behaviour": h})
