from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from schemas.message import LLMResponse, Message, TokenUsage


def extract_token_usage(raw: Any) -> TokenUsage | None:
    """Extract standard TokenUsage from various provider response formats."""
    if not raw:
        return None
    try:
        # OpenAI, Groq, Mistral, OpenRouter, Together, DeepSeek, etc.
        if hasattr(raw, "usage") and raw.usage:
            prompt = getattr(raw.usage, "prompt_tokens", None)
            completion = getattr(raw.usage, "completion_tokens", None)
            if prompt is not None or completion is not None:
                prompt = prompt or 0
                completion = completion or 0
                total = getattr(raw.usage, "total_tokens", 0) or (prompt + completion)
                cached = 0
                prompt_details = getattr(raw.usage, "prompt_tokens_details", None)
                if prompt_details:
                    cached = getattr(prompt_details, "cached_tokens", 0) or 0
                return TokenUsage(
                    prompt_tokens=prompt,
                    completion_tokens=completion,
                    total_tokens=total,
                    cached_tokens=cached,
                )

            # Anthropic input_tokens / output_tokens
            input_tokens = getattr(raw.usage, "input_tokens", None)
            output_tokens = getattr(raw.usage, "output_tokens", None)
            if input_tokens is not None or output_tokens is not None:
                input_tokens = input_tokens or 0
                output_tokens = output_tokens or 0
                cached = getattr(raw.usage, "cache_read_input_tokens", 0) or 0
                return TokenUsage(
                    prompt_tokens=input_tokens,
                    completion_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    cached_tokens=cached,
                )

        # Gemini SDK usage_metadata
        if hasattr(raw, "usage_metadata") and raw.usage_metadata:
            prompt = getattr(raw.usage_metadata, "prompt_token_count", 0) or 0
            completion = getattr(raw.usage_metadata, "candidates_token_count", 0) or 0
            total = getattr(raw.usage_metadata, "total_token_count", 0) or (prompt + completion)
            cached = getattr(raw.usage_metadata, "cached_content_token_count", 0) or 0
            return TokenUsage(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
                cached_tokens=cached,
            )

        # Dict format
        if isinstance(raw, dict):
            usage = raw.get("usage") or raw.get("usage_metadata")
            if isinstance(usage, dict):
                prompt = (
                    usage.get("prompt_tokens")
                    or usage.get("input_tokens")
                    or usage.get("prompt_token_count")
                    or 0
                )
                completion = (
                    usage.get("completion_tokens")
                    or usage.get("output_tokens")
                    or usage.get("candidates_token_count")
                    or 0
                )
                total = (
                    usage.get("total_tokens")
                    or usage.get("total_token_count")
                    or (prompt + completion)
                )
                cached = (
                    usage.get("cached_tokens")
                    or usage.get("cache_read_input_tokens")
                    or usage.get("cached_content_token_count")
                    or 0
                )
                return TokenUsage(
                    prompt_tokens=int(prompt),
                    completion_tokens=int(completion),
                    total_tokens=int(total),
                    cached_tokens=int(cached),
                )
    except Exception:
        pass
    return None


@dataclass
class ModelInfo:
    """Information about an available model."""

    id: str
    name: str
    context_length: int | None = None
    description: str | None = None


class LLMProvider(ABC):
    """
    Base interface for all LLM providers.
    """

    name: str
    model: str

    # Default models for this provider (can be overridden)
    DEFAULT_MODELS: list[str] = []

    @abstractmethod
    def generate(
        self,
        messages: list[Message],
        tools: list | None = None,
        stream: bool = False,
    ) -> LLMResponse:
        """
        Generate a response from the model.
        """
        pass

    def list_models(self) -> list[ModelInfo]:
        """
        List available models for this provider.
        Override in subclasses to fetch from API.
        Returns default models if not overridden.
        """
        return [ModelInfo(id=m, name=m) for m in self.DEFAULT_MODELS]

    @classmethod
    def get_default_models(cls) -> list[str]:
        """Get list of default model IDs."""
        return cls.DEFAULT_MODELS
