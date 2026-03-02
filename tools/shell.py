import subprocess
import sys
from typing import Any

from pydantic import BaseModel, Field

from tools.base import Tool

# Commands that are known to be interactive and need direct terminal access
INTERACTIVE_COMMANDS = [
    "npx create-",
    "npm create",
    "npm init",
    "yarn create",
    "pnpm create",
    "ng new",
    "vue create",
    "create-react-app",
    "django-admin startproject",
    "rails new",
    "cargo init",
    "go mod init",
    "python -m venv",
    "ssh ",
    "vim ",
    "nano ",
    "less ",
    "more ",
]


class ShellToolSchema(BaseModel):
    command: str = Field(..., description="The shell command to execute.")


class ShellTool(Tool):
    name = "shell"
    description = "Executes a shell command on the user's system. For interactive commands (like npx create-next-app), the command will run directly in the terminal allowing user interaction."
    args_schema = ShellToolSchema

    def _is_interactive(self, command: str) -> bool:
        """Check if a command is likely to be interactive."""
        cmd_lower = command.lower()
        for pattern in INTERACTIVE_COMMANDS:
            if pattern in cmd_lower:
                return True
        return False

    def run(self, arguments: dict[str, Any]) -> Any:
        try:
            command = arguments.get("command")
            if not command:
                return "Error: No command provided."

            # Check if this is an interactive command
            if self._is_interactive(command):
                print(f"\n[Running interactive command: {command}]\n")
                sys.stdout.flush()

                # Run interactively - let user interact directly
                result = subprocess.run(command, shell=True, check=False)

                if result.returncode == 0:
                    return "Command completed successfully (exit code 0)."
                else:
                    return f"Command completed with exit code {result.returncode}."

            # Non-interactive: capture output with UTF-8 encoding
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,  # 2 minute timeout for non-interactive commands
                encoding="utf-8",
                errors="replace",  # Replace undecodable chars instead of failing
            )

            output = ""
            if result.stdout:
                output += f"STDOUT:\n{result.stdout}\n"
            if result.stderr:
                output += f"STDERR:\n{result.stderr}\n"

            return output if output else f"Command completed with exit code {result.returncode}."

        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 120 seconds."
        except Exception as e:
            return f"Failed to execute command: {str(e)}"
