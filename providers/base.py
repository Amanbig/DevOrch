from abc import ABC, abstractmethod
from dataclasses import dataclass

from schemas.message import LLMResponse, Message


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
