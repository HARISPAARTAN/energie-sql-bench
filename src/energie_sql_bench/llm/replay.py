"""Replay: recorded responses and recorded result sets, no network and no database."""

from __future__ import annotations

from typing import Any

from energie_sql_bench.execute import ExecResult
from energie_sql_bench.gold import sql_sha256
from energie_sql_bench.llm.base import Completion, ProviderError, ReplayMiss, Request
from energie_sql_bench.records import Usage


class ReplayProvider:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._by_key = {
            (r["prompt_hash"], r["model"], int(r["repeat"]), int(r["attempt"])): r for r in responses
        }

    def describe(self) -> dict[str, Any]:
        return {"provider": "replay"}

    def complete(self, request: Request) -> Completion:
        record = self._by_key.get((request.prompt_hash, request.model, request.repeat, request.attempt))
        if record is None:
            raise ReplayMiss(
                f"keine Aufzeichnung für {request.item_id}, Wiederholung {request.repeat}, Versuch {request.attempt} "
                f"(prompt_hash {request.prompt_hash}): Prompt, Schema oder Code haben sich geändert"
            )
        if record.get("error"):
            raise ProviderError(record["error"])
        return Completion(
            record["text"],
            Usage.from_json(record["usage"]),
            float(record["llm_ms"]),
            dict(record.get("meta") or {}),
        )


class RecordedExecutor:
    def __init__(self, predictions: dict[str, dict[str, Any]]) -> None:
        self._predictions = predictions

    def run(self, sql: str) -> ExecResult:
        sha = sql_sha256(sql)
        if sha not in self._predictions:
            raise ReplayMiss(f"kein aufgezeichnetes Ergebnis für SQL {sha[:12]}")
        return ExecResult.from_json(self._predictions[sha])

    def close(self) -> None:
        return None
