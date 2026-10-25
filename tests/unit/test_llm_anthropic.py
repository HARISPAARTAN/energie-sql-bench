from types import SimpleNamespace

import pytest

from energie_sql_bench.config import AnthropicSettings
from energie_sql_bench.llm import anthropic as adapter
from energie_sql_bench.llm.anthropic import AnthropicProvider
from energie_sql_bench.llm.base import ProviderError, Request

SETTINGS = AnthropicSettings(("claude-haiku-5-5",), "low", 2000, True)
REQUEST = Request("q001-de", "claude-haiku-5-5", "SYSTEM", (("user", "Frage: x"),), "abc", 0, 0)


class FakeStream:
    def __init__(self, message: object) -> None:
        self.message = message

    def __enter__(self) -> "FakeStream":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get_final_message(self) -> object:
        return self.message


class FakeMessages:
    def __init__(self, message: object = None, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.message = message
        self.error = error

    def stream(self, **kwargs: object) -> FakeStream:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return FakeStream(self.message)


def message() -> SimpleNamespace:
    return SimpleNamespace(
        id="msg_1",
        model="claude-haiku-5-5",
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="```sql\nSELECT 1\n```")],
        usage=SimpleNamespace(
            input_tokens=12, cache_creation_input_tokens=3000, cache_read_input_tokens=0, output_tokens=40
        ),
    )


def test_request_has_no_sampling_parameters_and_caches_system() -> None:
    messages = FakeMessages(message())
    provider = AnthropicProvider(SETTINGS, "claude-haiku-5-5", client=SimpleNamespace(messages=messages))
    completion = provider.complete(REQUEST)
    kwargs = messages.calls[0]
    assert set(kwargs) == {"model", "max_tokens", "system", "messages", "output_config"}
    assert kwargs["output_config"] == {"effort": "low"}
    assert kwargs["max_tokens"] == 2000
    assert kwargs["system"] == [{"type": "text", "text": "SYSTEM", "cache_control": {"type": "ephemeral"}}]
    assert kwargs["messages"] == [{"role": "user", "content": "Frage: x"}]
    assert completion.text == "```sql\nSELECT 1\n```"
    assert completion.usage.cache_creation_tokens == 3000 and completion.usage.output_tokens == 40
    assert completion.meta["stop_reason"] == "end_turn"


def test_usage_maps_all_four_token_kinds() -> None:
    reply = message()
    reply.usage = SimpleNamespace(
        input_tokens=1, cache_creation_input_tokens=2, cache_read_input_tokens=3, output_tokens=4
    )
    provider = AnthropicProvider(
        SETTINGS, "claude-haiku-5-5", client=SimpleNamespace(messages=FakeMessages(reply))
    )
    usage = provider.complete(REQUEST).usage
    assert (
        usage.input_tokens,
        usage.cache_creation_tokens,
        usage.cache_read_tokens,
        usage.output_tokens,
    ) == (
        1,
        2,
        3,
        4,
    )


def test_no_cache_control_when_disabled() -> None:
    settings = AnthropicSettings(("claude-haiku-5-5",), "low", 2000, False)
    provider = AnthropicProvider(
        settings, "claude-haiku-5-5", client=SimpleNamespace(messages=FakeMessages(message()))
    )
    assert "cache_control" not in provider.request_kwargs(REQUEST)["system"][0]


def test_api_errors_become_provider_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "provider_errors", lambda: (RuntimeError,))
    messages = FakeMessages(error=RuntimeError("overloaded"))
    provider = AnthropicProvider(SETTINGS, "claude-haiku-5-5", client=SimpleNamespace(messages=messages))
    with pytest.raises(ProviderError, match="overloaded"):
        provider.complete(REQUEST)


def test_real_sdk_error_type_is_recognised() -> None:
    import anthropic

    assert adapter.provider_errors() == (anthropic.APIError,)


def test_missing_key_is_reported() -> None:
    with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider(SETTINGS, "claude-haiku-5-5", api_key=None)


def test_describe() -> None:
    provider = AnthropicProvider(
        SETTINGS, "claude-haiku-5-5", client=SimpleNamespace(messages=FakeMessages())
    )
    meta = provider.describe()
    assert meta["provider"] == "anthropic" and meta["model"] == "claude-haiku-5-5" and meta["effort"] == "low"
