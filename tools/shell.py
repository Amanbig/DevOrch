import subprocess
from typing import Any

from pydantic import BaseModel, Field

from tools.base import Tool


class ShellToolSchema(BaseModel):
    command: str = Field(..., description="The shell command to execute.")


class ShellTool(Tool):
    name = "shell"
    description = """\
Executes a shell command and captures its output.

Use this for short-lived commands that return output, such as:
- Package management: `npm install`, `pip install`, `cargo build`
- Version control: `git status`, `git add`, `git commit`, `git clone`
- File operations: `mkdir`, `cp`, `mv`, `rm`
- Inspecting output: `cat`, `echo`, `pwd`, `ls`

For long-running servers or interactive scaffold tools, use `open_terminal` instead."""
    args_schema = ShellToolSchema

    def run(self, arguments: dict[str, Any]) -> Any:
        try:
            command = arguments.get("command")
            if not command:
                return "Error: No command provided."

            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
                encoding="utf-8",
                errors="replace",
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
