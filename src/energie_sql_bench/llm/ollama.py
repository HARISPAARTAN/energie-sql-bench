"""Ollama adapter (local REST /api/chat): temperature 0, fixed seed, explicit num_ctx, model digest recorded."""

from __future__ import annotations

import time
from typing import Any

import httpx

from energie_sql_bench.config import OllamaSettings
from energie_sql_bench.llm.base import Completion, ProviderError, Request
from energie_sql_bench.records import Usage


class OllamaProvider:
    def __init__(self, settings: OllamaSettings, model: str, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._model = model
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
            "options": {"temperature": 0, "seed": self._settings.seed, "num_ctx": self._settings.num_ctx},
        }
        start = time.perf_counter()
        try:
            response = self._client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"{type(exc).__name__}: {exc}") from exc
        llm_ms = round((time.perf_counter() - start) * 1000.0, 3)
        usage = Usage(int(data.get("prompt_eval_count", 0) or 0), 0, 0, int(data.get("eval_count", 0) or 0))
        return Completion(
            data["message"]["content"], usage, llm_ms, {"total_duration_ns": data.get("total_duration")}
        )
