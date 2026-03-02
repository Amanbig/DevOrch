from abc import ABC, abstractmethod
from typing import List, Optional, Dict
from dataclasses import dataclass

from schemas.message import Message, LLMResponse


@dataclass
class ModelInfo:
    """Information about an available model."""
    id: str
    name: str
    context_length: Optional[int] = None
    description: Optional[str] = None


class LLMProvider(ABC):
    """
    Base interface for all LLM providers.
    """

    name: str
    model: str

    # Default models for this provider (can be overridden)
    DEFAULT_MODELS: List[str] = []

    @abstractmethod
    def generate(
        self,
        messages: List[Message],
        tools: Optional[list] = None,
        stream: bool = False,
    ) -> LLMResponse:
        """
        Generate a response from the model.
        """
        pass

    def list_models(self) -> List[ModelInfo]:
        """
        List available models for this provider.
        Override in subclasses to fetch from API.
        Returns default models if not overridden.
        """
        return [ModelInfo(id=m, name=m) for m in self.DEFAULT_MODELS]

    @classmethod
    def get_default_models(cls) -> List[str]:
        """Get list of default model IDs."""
        return cls.DEFAULT_MODELS