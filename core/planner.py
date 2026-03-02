from abc import ABC, abstractmethod
from typing import List

from schemas.message import Message


class Planner(ABC):
    """
    Decides the next step for the agent.
    """

    @abstractmethod
    def plan(self, history: List[Message]) -> List[Message]:
        """
        Returns updated messages to send to the LLM.
        """
        pass