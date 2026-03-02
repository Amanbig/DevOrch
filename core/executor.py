from abc import ABC, abstractmethod
from typing import Dict, Any, List
import json
import logging
from rich.console import Console
from rich.prompt import Confirm

from tools.base import Tool

logger = logging.getLogger(__name__)
console = Console()

class Executor(ABC):
    """
    Executes tool calls safely.
    """

    @abstractmethod
    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        pass


class ToolExecutor(Executor):
    def __init__(self, tools: List[Tool], require_confirmation: bool = True):
        self.tools = {tool.name: tool for tool in tools}
        self.require_confirmation = require_confirmation

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        if tool_name not in self.tools:
            return f"Error: Tool '{tool_name}' not found."
        
        tool = self.tools[tool_name]
        try:
            # UI prompt for dangerous tools
            if self.require_confirmation and tool_name == "shell":
                command = arguments.get("command", "")
                console.print(f"\n[bold yellow]⚠️  DevPilot wants to run a shell command:[/bold yellow]")
                console.print(f"  > [bold cyan]{command}[/bold cyan]")
                if not Confirm.ask("Allow this command?"):
                    console.print("[yellow]Command cancelled by user.[/yellow]")
                    return "Error: User denied permission to execute this command."

            # We don't print the execution status here anymore, we'll let the agent handle the spinner.
            result = tool.run(arguments)
            return str(result)
        except Exception as e:
            return f"Error executing {tool_name}: {str(e)}"
