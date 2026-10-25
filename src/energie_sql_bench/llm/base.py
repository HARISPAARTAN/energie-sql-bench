"""Provider protocol and the request and completion types shared by all adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from energie_sql_bench.records import Usage


@dataclass(frozen=True)
class Request:
    item_id: str
    model: str
    system: str
    messages: tuple[tuple[str, str], ...]
    prompt_hash: str
    repeat: int
    attempt: int


@dataclass(frozen=True)
class Completion:
    text: str
    usage: Usage
    llm_ms: float
    meta: dict[str, Any] = field(default_factory=dict)
    prompt_tokens_known: bool = True  # False: the provider did not report a usable prompt size (fail closed)


class ProviderError(RuntimeError):
    """The provider failed after its own retries (network, overload, API error). Counted, never fatal alone."""


class ReplayMiss(LookupError):
    """A recorded response or result is missing: prompt, gold or code changed since the recording."""


class Provider(Protocol):
    def complete(self, request: Request) -> Completion: ...

    def describe(self) -> dict[str, Any]: ...
