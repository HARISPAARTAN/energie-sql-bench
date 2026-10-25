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
    assert body["options"] == {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 1000}
    assert body["stream"] is False
    assert body["messages"][0] == {"role": "system", "content": "SYSTEM"}
    return httpx.Response(
        200,
        json={
            "message": {"content": "```sql\nSELECT 1\n```"},
            "prompt_eval_count": 900,
            "eval_count": 30,
            "done_reason": "stop",
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
    assert completion.prompt_tokens_known
    assert completion.meta == {"done_reason": "stop", "prompt_eval_count": 900, "total_duration_ns": 5}


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


def chat(**fields: object) -> OllamaProvider:
    body = {"message": {"content": "```sql\nSELECT 1\n```"}, "eval_count": 30, **fields}
    return provider(lambda r: httpx.Response(200, json=body))


@pytest.mark.parametrize("fields", [{}, {"prompt_eval_count": None}, {"prompt_eval_count": 0}])
def test_missing_or_zero_prompt_count_is_unknown_not_zero(fields: dict[str, object]) -> None:
    completion = chat(**fields).complete(REQUEST)
    assert not completion.prompt_tokens_known
    assert completion.text.startswith("```sql") and completion.usage.output_tokens == 30


def test_a_reported_prompt_count_is_known() -> None:
    assert chat(prompt_eval_count=1).complete(REQUEST).prompt_tokens_known


def test_num_predict_is_sent_and_done_reason_recorded() -> None:
    seen: list[dict] = []

    def capture(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200, json={"message": {"content": "x"}, "prompt_eval_count": 5, "done_reason": "length"}
        )

    client = httpx.Client(base_url=SETTINGS.host, transport=httpx.MockTransport(capture))
    completion = OllamaProvider(SETTINGS, "qwen2.5-coder:7b", client=client, num_predict=321).complete(
        REQUEST
    )
    assert seen[0]["options"]["num_predict"] == 321
    assert completion.meta["done_reason"] == "length"


def test_describe_records_num_predict() -> None:
    assert provider().describe()["num_predict"] == 1000


@pytest.mark.parametrize("body", [{"nothing": 1}, {"message": {}}, [1, 2]])
def test_malformed_body_becomes_provider_error(body: object) -> None:
    with pytest.raises(ProviderError):
        provider(lambda r: httpx.Response(200, json=body)).complete(REQUEST)


def test_non_json_body_becomes_provider_error() -> None:
    with pytest.raises(ProviderError):
        provider(lambda r: httpx.Response(200, text="<html>")).complete(REQUEST)
