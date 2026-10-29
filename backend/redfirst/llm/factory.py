"""Select the configured provider. New providers are added here, not in business logic."""

from redfirst.core.config import Settings
from redfirst.llm.base import LLMProvider


def make_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        from redfirst.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings)
    raise ValueError(f"unknown LLM provider: {settings.llm_provider!r}")
