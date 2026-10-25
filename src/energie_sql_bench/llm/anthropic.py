"""Anthropic adapter on the official SDK (1.x): streaming, prompt caching on the static system prefix,
output_config.effort. No temperature, top_p, top_k or thinking parameters (rejected or unneeded on the 5.5
models) and no server-side fallbacks (another model answering would corrupt the measurement)."""

from __future__ import annotations

import time
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from energie_sql_bench.config import AnthropicSettings
from energie_sql_bench.llm.base import Completion, ProviderError, Request
from energie_sql_bench.records import Usage


def provider_errors() -> tuple[type[BaseException], ...]:
    import anthropic

    return (anthropic.APIError,)


def _sdk_version() -> str:
    try:
        return version("anthropic")
    except PackageNotFoundError:
        return "unknown"


class AnthropicProvider:
    def __init__(
        self, settings: AnthropicSettings, model: str, api_key: str | None = None, client: Any = None
    ) -> None:
        if client is None:
            if not api_key:
                raise ProviderError("ANTHROPIC_API_KEY fehlt in .env")
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=120.0)
        self._client = client
        self._settings = settings
        self._model = model

    def describe(self) -> dict[str, Any]:
        return {
            "cache": self._settings.cache,
            "effort": self._settings.effort,
            "max_tokens": self._settings.max_tokens,
            "model": self._model,
            "provider": "anthropic",
            "sdk": _sdk_version(),
        }

    def request_kwargs(self, request: Request) -> dict[str, Any]:
        system_block: dict[str, Any] = {"type": "text", "text": request.system}
        if self._settings.cache:
            system_block["cache_control"] = {"type": "ephemeral"}
        return {
            "model": self._model,
            "max_tokens": self._settings.max_tokens,
            "system": [system_block],
            "messages": [{"role": role, "content": content} for role, content in request.messages],
            "output_config": {"effort": self._settings.effort},
        }

    def complete(self, request: Request) -> Completion:
        start = time.perf_counter()
        try:
            with self._client.messages.stream(**self.request_kwargs(request)) as stream:
                message = stream.get_final_message()
        except provider_errors() as exc:
            raise ProviderError(f"{type(exc).__name__}: {exc}") from exc
        llm_ms = round((time.perf_counter() - start) * 1000.0, 3)
        text = "".join(
            getattr(block, "text", "") for block in message.content if getattr(block, "type", "") == "text"
        )
        u = message.usage
        usage = Usage(
            int(getattr(u, "input_tokens", 0) or 0),
            int(getattr(u, "cache_creation_input_tokens", 0) or 0),
            int(getattr(u, "cache_read_input_tokens", 0) or 0),
            int(getattr(u, "output_tokens", 0) or 0),
        )
        meta = {"id": message.id, "model": message.model, "stop_reason": message.stop_reason}
        return Completion(text, usage, llm_ms, meta)
