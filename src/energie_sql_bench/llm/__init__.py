"""LLM adapters. A new provider is one module with complete() and describe() plus a row in pricing.toml."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from energie_sql_bench.config import Settings
    from energie_sql_bench.llm.base import Provider
    from energie_sql_bench.questions import Question


def default_model(name: str, settings: Settings) -> str:
    from energie_sql_bench.llm.synthetic import SYNTHETIC_MODEL

    if name == "ollama":
        return settings.ollama.model
    if name == "synthetic":
        return SYNTHETIC_MODEL
    if name == "anthropic":
        return settings.anthropic.models[0]
    raise ValueError(f"unbekannter Provider {name}")


def make_provider(name: str, model: str, settings: Settings, questions: list[Question]) -> Provider:
    if name == "anthropic":
        from energie_sql_bench.llm.anthropic import AnthropicProvider

        return AnthropicProvider(settings.anthropic, model, settings.env.get("ANTHROPIC_API_KEY"))
    if name == "ollama":
        from energie_sql_bench.llm.ollama import OllamaProvider

        return OllamaProvider(
            settings.ollama, model, num_predict=settings.prompt_budget.output_reserve_tokens
        )
    if name == "synthetic":
        from energie_sql_bench.llm.synthetic import SyntheticProvider

        return SyntheticProvider(questions)
    raise ValueError(f"unbekannter Provider {name}")
