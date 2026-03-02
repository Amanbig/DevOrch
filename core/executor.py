from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from rich.prompt import Prompt

from tools.base import Tool
from config.permissions import (
    get_permissions, PermissionLevel, PermissionChoice, Permissions
)
from utils.logger import get_console, print_warning, print_success, print_info

console = get_console()


class Executor(ABC):
    """
    Executes tool calls safely.
    """

    @abstractmethod
    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        pass


class ToolExecutor(Executor):
    def __init__(
        self,
        tools: List[Tool],
        require_confirmation: bool = True,
        permissions: Optional[Permissions] = None
    ):
        self.tools = {tool.name: tool for tool in tools}
        self.require_confirmation = require_confirmation
        self.permissions = permissions or get_permissions()

    def _get_command_description(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Get a human-readable description of the command."""
        if tool_name == "shell":
            return arguments.get("command", "")
        elif tool_name == "filesystem":
            action = arguments.get("action", "")
            path = arguments.get("path", "")
            if action == "write":
                return f"write to {path}"
            elif action == "read":
                return f"read {path}"
            elif action == "list":
                return f"list {path}"
            return f"{action} {path}"
        else:
            return str(arguments)

    def _ask_permission(
        self,
        tool_name: str,
        command: str,
        reason: Optional[str] = None
    ) -> PermissionChoice:
        """Ask user for permission to execute a command."""
        console.print()
        print_warning(f"DevPilot wants to use [bold]{tool_name}[/bold]:")
        console.print(f"  [bold cyan]{command}[/bold cyan]")

        if reason:
            console.print(f"  [dim]{reason}[/dim]")

        console.print()
        console.print("  [dim]1.[/dim] Allow once")
        console.print("  [dim]2.[/dim] Allow for this session")
        console.print("  [dim]3.[/dim] Always allow (save to config)")
        console.print("  [dim]4.[/dim] Deny")
        console.print()

        choice = Prompt.ask(
            "Choose",
            choices=["1", "2", "3", "4", "y", "n"],
            default="1"
        )

        choice_map = {
            "1": PermissionChoice.ALLOW_ONCE,
            "y": PermissionChoice.ALLOW_ONCE,
            "2": PermissionChoice.ALLOW_SESSION,
            "3": PermissionChoice.ALLOW_ALWAYS,
            "4": PermissionChoice.DENY,
            "n": PermissionChoice.DENY,
        }

        return choice_map.get(choice, PermissionChoice.DENY)

    def _handle_permission_choice(
        self,
        choice: PermissionChoice,
        tool_name: str,
        command: str
    ) -> bool:
        """Handle the user's permission choice. Returns True if allowed."""
        if choice == PermissionChoice.ALLOW_ONCE:
            return True

        elif choice == PermissionChoice.ALLOW_SESSION:
            # Create a pattern from the command
            pattern = self._create_pattern(command)
            self.permissions.add_allowed_pattern(tool_name, pattern, session_only=True)
            print_info(f"Allowed for this session: {pattern}")
            return True

        elif choice == PermissionChoice.ALLOW_ALWAYS:
            pattern = self._create_pattern(command)
            self.permissions.add_allowed_pattern(tool_name, pattern, session_only=False)
            print_success(f"Saved to config: always allow '{pattern}'")
            return True

        else:  # DENY
            print_warning("Command denied.")
            return False

    def _create_pattern(self, command: str) -> str:
        """Create a pattern from a command for future matching."""
        # For simple commands, use the exact command
        # For commands with arguments, use the base command + wildcard
        parts = command.strip().split()
        if len(parts) <= 1:
            return command.strip()

        # Common patterns: use first 1-2 words + wildcard
        base = parts[0]

        # Git commands: git <subcommand> *
        if base == "git" and len(parts) > 1:
            return f"git {parts[1]}*"

        # npm/pip commands: npm <subcommand> *
        if base in ("npm", "pip", "pip3", "cargo", "go") and len(parts) > 1:
            return f"{base} {parts[1]}*"

        # Python/node: python <script>
        if base in ("python", "python3", "node"):
            return f"{base}*"

        # Default: first word + wildcard
        return f"{base}*"

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        if tool_name not in self.tools:
            return f"Error: Tool '{tool_name}' not found."

        tool = self.tools[tool_name]
        command = self._get_command_description(tool_name, arguments)

        try:
            # Check permissions if confirmation is required
            if self.require_confirmation:
                perm_level, reason = self.permissions.check_permission(tool_name, command)

                if perm_level == PermissionLevel.DENY:
                    print_warning(f"Command blocked: {reason or 'denied by policy'}")
                    return f"Error: Command denied - {reason or 'blocked by permission policy'}"

                elif perm_level == PermissionLevel.ASK:
                    choice = self._ask_permission(tool_name, command, reason)
                    if not self._handle_permission_choice(choice, tool_name, command):
                        return "Error: User denied permission to execute this command."

                # ALLOW - proceed silently

            # Execute the tool
            result = tool.run(arguments)
            return str(result)

        except Exception as e:
            return f"Error executing {tool_name}: {str(e)}"
