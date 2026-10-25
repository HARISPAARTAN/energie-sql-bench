import json
from collections.abc import Callable

import httpx
import pytest

from energie_sql_bench.config import OllamaSettings
from energie_sql_bench.llm.base import ProviderError, Request
from energie_sql_bench.llm.ollama import OllamaProvider

SETTINGS = OllamaSettings("http://ollama.test", "qwen2.5-coder:7b", 8192, 42)
REQUEST = Request("q001-en", "qwen2.5-coder:7b", "SYSTEM", (("user", "Question: x"),), "abc", 0, 0)


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/tags":
        return httpx.Response(200, json={"models": [{"name": "qwen2.5-coder:7b", "digest": "sha256:abc"}]})
    body = json.loads(request.content)
    assert body["options"] == {"temperature": 0, "seed": 42, "num_ctx": 8192}
    assert body["stream"] is False
    assert body["messages"][0] == {"role": "system", "content": "SYSTEM"}
    return httpx.Response(
        200,
        json={
            "message": {"content": "```sql\nSELECT 1\n```"},
            "prompt_eval_count": 900,
            "eval_count": 30,
            "total_duration": 5,
        },
    )


def provider(h: Callable[[httpx.Request], httpx.Response] = handler) -> OllamaProvider:
    client = httpx.Client(base_url=SETTINGS.host, transport=httpx.MockTransport(h))
    return OllamaProvider(SETTINGS, "qwen2.5-coder:7b", client=client)


def test_chat_request_and_usage() -> None:
    completion = provider().complete(REQUEST)
    assert completion.text == "```sql\nSELECT 1\n```"
    assert completion.usage.input_tokens == 900 and completion.usage.output_tokens == 30


def test_describe_records_digest() -> None:
    assert provider().describe()["digest"] == "sha256:abc"


def test_describe_survives_an_unreachable_server() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    meta = provider(refuse).describe()
    assert meta["digest"] is None and meta["num_ctx"] == 8192 and meta["seed"] == 42


def test_http_error_becomes_provider_error() -> None:
    with pytest.raises(ProviderError):
        provider(lambda r: httpx.Response(500, text="boom")).complete(REQUEST)
