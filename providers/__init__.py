from typing import Optional

from providers.base import LLMProvider
from providers.openai import OpenAIProvider
from providers.anthropic import AnthropicProvider
from providers.gemini import GeminiProvider
from providers.local import LocalProvider


PROVIDERS = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "local": LocalProvider,
}


def get_provider(
    name: str,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    **kwargs
) -> LLMProvider:
    """
    Factory function to get a provider instance.

    Args:
        name: Provider name (openai, anthropic, gemini, local)
        model: Model name (optional, uses provider default)
        api_key: API key (optional, uses env var)
        **kwargs: Additional provider-specific arguments (e.g., base_url for local)

    Returns:
        An LLMProvider instance

    Raises:
        ValueError: If provider name is unknown
    """
    if name not in PROVIDERS:
        available = ", ".join(PROVIDERS.keys())
        raise ValueError(f"Unknown provider: {name}. Available: {available}")

    provider_class = PROVIDERS[name]

    init_kwargs = {}
    if model:
        init_kwargs["model"] = model
    if api_key:
        init_kwargs["api_key"] = api_key
    init_kwargs.update(kwargs)

    return provider_class(**init_kwargs)


__all__ = [
    "LLMProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "LocalProvider",
    "get_provider",
    "PROVIDERS",
]
