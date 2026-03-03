from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Optional

import questionary
from questionary import Style as QStyle
from rich.panel import Panel
from rich.text import Text

from config.permissions import PermissionChoice, PermissionLevel, Permissions, get_permissions
from tools.base import Tool
from utils.logger import get_console, print_success, print_warning

if TYPE_CHECKING:
    from core.modes import ModeManager

console = get_console()

# Custom style for questionary prompts
PROMPT_STYLE = QStyle(
    [
        ("qmark", "fg:yellow bold"),
        ("question", "fg:white bold"),
        ("answer", "fg:green bold"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),  # Normal white text, no background - arrow shows selection
        ("selected", "fg:cyan bold"),
    ]
)


class Executor(ABC):
    """
    Executes tool calls safely.
    """

    @abstractmethod
    def execute(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        pass


class ToolExecutor(Executor):
    def __init__(
        self,
        tools: list[Tool],
        require_confirmation: bool = True,
        permissions: Permissions | None = None,
        mode_manager: Optional["ModeManager"] = None,
    ):
        self.tools = {tool.name: tool for tool in tools}
        self.require_confirmation = require_confirmation
        self.permissions = permissions or get_permissions()
        self.mode_manager = mode_manager

    def _get_command_description(self, tool_name: str, arguments: dict[str, Any]) -> str:
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
        self, tool_name: str, command: str, reason: str | None = None
    ) -> PermissionChoice:
        """Ask user for permission to execute a command using interactive selection."""
        console.print()

        # Create a nice panel for the command
        command_display = Text()
        command_display.append("Tool: ", style="dim")
        command_display.append(f"{tool_name}\n", style="bold yellow")
        command_display.append("Command: ", style="dim")
        command_display.append(command, style="bold cyan")

        if reason:
            command_display.append(f"\n{reason}", style="dim italic")

        panel = Panel(
            command_display,
            title="[bold yellow]Permission Required[/bold yellow]",
            border_style="yellow",
            padding=(0, 1),
        )
        console.print(panel)

        # Use questionary for interactive selection
        choices = [
            questionary.Choice("Allow once", value=PermissionChoice.ALLOW_ONCE),
            questionary.Choice("Allow for this session", value=PermissionChoice.ALLOW_SESSION),
            questionary.Choice(
                "Always allow (save to config)", value=PermissionChoice.ALLOW_ALWAYS
            ),
            questionary.Choice("Deny", value=PermissionChoice.DENY),
        ]

        try:
            result = questionary.select(
                "Choose an action:",
                choices=choices,
                default=choices[0],
                style=PROMPT_STYLE,
                instruction="(Use arrow keys to navigate, Enter to select)",
            ).ask()

            if result is None:  # User pressed Ctrl+C
                return PermissionChoice.DENY

            return result

        except (KeyboardInterrupt, EOFError):
            return PermissionChoice.DENY

    def _handle_permission_choice(
        self, choice: PermissionChoice, tool_name: str, command: str
    ) -> bool:
        """Handle the user's permission choice. Returns True if allowed."""
        if choice == PermissionChoice.ALLOW_ONCE:
            print_success("Allowed once")
            return True

        elif choice == PermissionChoice.ALLOW_SESSION:
            # Create a pattern from the command
            pattern = self._create_pattern(command)
            self.permissions.add_allowed_pattern(tool_name, pattern, session_only=True)
            print_success(f"Allowed for session: {pattern}")
            return True

        elif choice == PermissionChoice.ALLOW_ALWAYS:
            pattern = self._create_pattern(command)
            self.permissions.add_allowed_pattern(tool_name, pattern, session_only=False)
            print_success(f"Saved to config: always allow '{pattern}'")
            return True

        else:  # DENY
            print_warning("Command denied")
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

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name not in self.tools:
            return f"Error: Tool '{tool_name}' not found."

        tool = self.tools[tool_name]
        command = self._get_command_description(tool_name, arguments)

        try:
            # Check if we should ask for permission based on mode
            should_ask = self.require_confirmation
            if self.mode_manager and not self.mode_manager.should_ask_permission():
                should_ask = False

            # Check permissions if confirmation is required
            if should_ask:
                perm_level, reason = self.permissions.check_permission(tool_name, command)

                if perm_level == PermissionLevel.DENY:
                    print_warning(f"Command blocked: {reason or 'denied by policy'}")
                    return f"Error: Command denied - {reason or 'blocked by permission policy'}"

                elif perm_level == PermissionLevel.ASK:
                    choice = self._ask_permission(tool_name, command, reason)
                    if not self._handle_permission_choice(choice, tool_name, command):
                        return "Error: User denied permission to execute this command."

                # ALLOW - proceed silently
            else:
                # Even in auto mode, check for dangerous commands
                perm_level, reason = self.permissions.check_permission(tool_name, command)
                if perm_level == PermissionLevel.DENY:
                    print_warning(f"Command blocked (dangerous): {reason or 'denied by policy'}")
                    return f"Error: Command denied - {reason or 'blocked by permission policy'}"

            # Execute the tool
            result = tool.run(arguments)
            return str(result)

        except Exception as e:
            return f"Error executing {tool_name}: {str(e)}"
