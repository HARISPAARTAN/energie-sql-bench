"""Ollama adapter (local REST /api/chat): temperature 0, fixed seed, explicit num_ctx, model digest recorded."""

from __future__ import annotations

import time
from typing import Any

import httpx

from energie_sql_bench.config import OllamaSettings
from energie_sql_bench.llm.base import Completion, ProviderError, Request
from energie_sql_bench.records import Usage

DEFAULT_NUM_PREDICT = 1000  # the output reserve of [prompt_budget]; a looping model must not fill the context


def _count(value: Any) -> int | None:
    """A token count as reported, or None when Ollama left it out, sent null, 0 or something unusable."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


class OllamaProvider:
    def __init__(
        self,
        settings: OllamaSettings,
        model: str,
        client: httpx.Client | None = None,
        num_predict: int = DEFAULT_NUM_PREDICT,
    ) -> None:
        self._settings = settings
        self._model = model
        self._num_predict = num_predict
        self._client = client or httpx.Client(base_url=settings.host, timeout=600.0)

    def describe(self) -> dict[str, Any]:
        digest = None
        try:
            response = self._client.get("/api/tags")
            response.raise_for_status()
            for entry in response.json().get("models", []):
                if self._model in (entry.get("name"), entry.get("model")):
                    digest = entry.get("digest")
        except httpx.HTTPError:
            digest = None
        return {
            "digest": digest,
            "model": self._model,
            "num_ctx": self._settings.num_ctx,
            "num_predict": self._num_predict,
            "provider": "ollama",
            "seed": self._settings.seed,
            "temperature": 0,
        }

    def complete(self, request: Request) -> Completion:
        payload = {
            "model": self._model,
            "messages": [{"role": "system", "content": request.system}]
            + [{"role": role, "content": content} for role, content in request.messages],
            "stream": False,
            "options": {
                "temperature": 0,
                "seed": self._settings.seed,
                "num_ctx": self._settings.num_ctx,
                "num_predict": self._num_predict,
            },
        }
        start = time.perf_counter()
        try:
            response = self._client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:  # ValueError: the body is not JSON
            raise ProviderError(f"{type(exc).__name__}: {exc}") from exc
        llm_ms = round((time.perf_counter() - start) * 1000.0, 3)
        try:
            text = data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise ProviderError(f"Antwort ohne message.content: {str(data)[:200]}") from exc
        # Ollama leaves prompt_eval_count out (or reports only the newly evaluated tokens) when the prompt is
        # served from its cache: an unusable count is unknown, never 0, and the runner fails the budget closed.
        prompt = _count(data.get("prompt_eval_count"))
        usage = Usage(prompt or 0, 0, 0, int(data.get("eval_count", 0) or 0))
        meta = {
            "done_reason": data.get("done_reason"),
            "prompt_eval_count": data.get("prompt_eval_count"),
            "total_duration_ns": data.get("total_duration"),
        }
        return Completion(text, usage, llm_ms, meta, prompt_tokens_known=prompt is not None)
