from abc import ABC, abstractmethod

from schemas.message import Message


class Planner(ABC):
    """
    Decides the next step for the agent.
    """

    @abstractmethod
    def plan(self, history: list[Message]) -> list[Message]:
        """
        Returns updated messages to send to the LLM.
        """
        pass
