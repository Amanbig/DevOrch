from abc import ABC, abstractmethod
from typing import Dict, Any, List
import json
import logging

from tools.base import Tool

logger = logging.getLogger(__name__)

class Executor(ABC):
    """
    Executes tool calls safely.
    """

    @abstractmethod
    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        pass


class ToolExecutor(Executor):
    def __init__(self, tools: List[Tool]):
        self.tools = {tool.name: tool for tool in tools}

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        if tool_name not in self.tools:
            return f"Error: Tool '{tool_name}' not found."
        
        tool = self.tools[tool_name]
        try:
            logger.info(f"Executing {tool_name} with {json.dumps(arguments)}")
            result = tool.run(arguments)
            return str(result)
        except Exception as e:
            logger.error(f"Error executing {tool_name}: {str(e)}")
            return f"Error executing {tool_name}: {str(e)}"
