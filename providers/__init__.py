from typing import Optional, List, Dict, Type

from providers.base import LLMProvider, ModelInfo
from providers.openai import OpenAIProvider
from providers.anthropic import AnthropicProvider
from providers.gemini import GeminiProvider
from providers.local import LocalProvider
from providers.openrouter import OpenRouterProvider
from providers.mistral import MistralProvider
from providers.groq import GroqProvider
from providers.lmstudio import LMStudioProvider
from providers.together import TogetherProvider


# All available providers
PROVIDERS: Dict[str, Type[LLMProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "local": LocalProvider,
    "openrouter": OpenRouterProvider,
    "mistral": MistralProvider,
    "groq": GroqProvider,
    "lmstudio": LMStudioProvider,
    "together": TogetherProvider,
}

# Provider descriptions for help
PROVIDER_INFO = {
    "openai": "OpenAI - GPT-4o, GPT-4, etc.",
    "anthropic": "Anthropic - Claude 3.5, Claude 3, etc.",
    "gemini": "Google - Gemini Pro, Flash, etc.",
    "local": "Ollama - Local models (llama, mistral, etc.)",
    "openrouter": "OpenRouter - Access 100+ models via one API",
    "mistral": "Mistral AI - Mistral Large, Medium, Codestral",
    "groq": "Groq - Ultra-fast inference (Llama, Mixtral)",
    "lmstudio": "LM Studio - Run local models with UI",
    "together": "Together AI - Open source models at scale",
}

# Environment variable names for API keys
PROVIDER_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "local": None,
    "openrouter": "OPENROUTER_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "lmstudio": None,
    "together": "TOGETHER_API_KEY",
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


def get_default_models(provider_name: str) -> List[str]:
    """Get default model list for a provider."""
    if provider_name not in PROVIDERS:
        return []
    return PROVIDERS[provider_name].DEFAULT_MODELS


__all__ = [
    "LLMProvider",
    "ModelInfo",
    "OpenAIProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "LocalProvider",
    "OpenRouterProvider",
    "MistralProvider",
    "GroqProvider",
    "LMStudioProvider",
    "TogetherProvider",
    "get_provider",
    "get_default_models",
    "PROVIDERS",
    "PROVIDER_INFO",
    "PROVIDER_ENV_VARS",
]
