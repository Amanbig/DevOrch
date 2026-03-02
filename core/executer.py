from abc import ABC, abstractmethod
from typing import Dict, Any


class Executor(ABC):
    """
    Executes tool calls safely.
    """

    @abstractmethod
    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        pass