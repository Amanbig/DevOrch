from abc import ABC, abstractmethod
from typing import Dict, Any, Type
from pydantic import BaseModel

class Tool(ABC):
    """
    Base class for all tools.
    """
    name: str = ""
    description: str = ""
    args_schema: Type[BaseModel] = None

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
        parameters = {"type": "object", "properties": {}}
        if self.args_schema:
            schema_dump = self.args_schema.model_json_schema()
            parameters = {
                "type": "object",
                "properties": schema_dump.get("properties", {}),
                "required": schema_dump.get("required", [])
            }
            
        return {
            "name": self.name,
            "description": self.description,
            "parameters": parameters,
        }