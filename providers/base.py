from abc import ABC, abstractmethod
from typing import List, Optional

from schemas.message import Message, LLMResponse


class LLMProvider(ABC):
    """
    Base interface for all LLM providers.
    """

    name: str

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