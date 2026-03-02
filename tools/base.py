from abc import ABC, abstractmethod
from typing import Dict, Any


class Tool(ABC):
    """
    Base class for all tools.
    """

    name: str
    description: str

    @abstractmethod
    def run(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute the tool with given arguments.
        """
        pass

    def schema(self) -> Dict[str, Any]:
        """
        JSON schema exposed to LLMs.
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {},
            },
        }