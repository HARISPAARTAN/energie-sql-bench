"""Records of one benchmark run: token usage, attempts, item outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STATUSES = (
    "ok",
    "truncated",
    "abstain",
    "no_sql",
    "parse_error",
    "blocked",
    "db_error",
    "timeout",
    "provider_error",
)
REPAIRABLE = frozenset({"parse_error", "blocked", "db_error"})


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.cache_creation_tokens + other.cache_creation_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.output_tokens + other.output_tokens,
        )

    def to_json(self) -> dict[str, int]:
        return {
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Usage:
        return cls(
            int(data.get("input_tokens", 0)),
            int(data.get("cache_creation_tokens", 0)),
            int(data.get("cache_read_tokens", 0)),
            int(data.get("output_tokens", 0)),
        )


@dataclass(frozen=True)
class AttemptRecord:
    attempt: int
    prompt_hash: str
    status: str
    sql: str | None
    sql_sha256: str | None
    guard_reason: str | None
    error: str | None
    usage: Usage
    llm_ms: float
    db_ms: float

    def to_json(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "db_ms": self.db_ms,
            "error": self.error,
            "guard_reason": self.guard_reason,
            "llm_ms": self.llm_ms,
            "prompt_hash": self.prompt_hash,
            "sql": self.sql,
            "sql_sha256": self.sql_sha256,
            "status": self.status,
            "usage": self.usage.to_json(),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> AttemptRecord:
        return cls(
            int(data["attempt"]),
            data["prompt_hash"],
            data["status"],
            data.get("sql"),
            data.get("sql_sha256"),
            data.get("guard_reason"),
            data.get("error"),
            Usage.from_json(data["usage"]),
            float(data["llm_ms"]),
            float(data["db_ms"]),
        )


@dataclass(frozen=True)
class Outcome:
    item_id: str
    question_id: str
    lang: str
    tier: str
    expect: str
    repeat: int
    attempts: tuple[AttemptRecord, ...]
    final_status: str
    correct: bool
    strict: bool
    extra_columns: int
    reason: str
    labels: tuple[str, ...]
    cost_usd: float

    def to_json(self) -> dict[str, Any]:
        return {
            "attempts": [a.to_json() for a in self.attempts],
            "correct": self.correct,
            "cost_usd": round(self.cost_usd, 8),
            "expect": self.expect,
            "extra_columns": self.extra_columns,
            "final_status": self.final_status,
            "item_id": self.item_id,
            "labels": list(self.labels),
            "lang": self.lang,
            "question_id": self.question_id,
            "reason": self.reason,
            "repeat": self.repeat,
            "strict": self.strict,
            "tier": self.tier,
        }
