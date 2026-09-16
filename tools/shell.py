import platform
import re
import subprocess
from typing import Any

from pydantic import BaseModel, Field

from tools.base import Tool


def normalize_windows_command(command: str) -> str:
    """Normalize common Unix shell commands when executing on Windows cmd.exe."""
    # Split on logical operators (&&, ||, &, ;) while preserving delimiters
    parts = re.split(r"(\s*(?:&&|\|\||&|;)\s*)", command)
    normalized = []
    for part in parts:
        stripped = part.strip()
        if stripped in ("&&", "||", "&", ";"):
            normalized.append(part)
            continue
        tokens = stripped.split(None, 1)
        if not tokens:
            normalized.append(part)
            continue
        cname = tokens[0].lower()
        rest = tokens[1] if len(tokens) > 1 else ""

        if cname == "pwd" and not rest:
            normalized.append("cd")
        elif cname == "ls":
            # Strip unix-specific flags like -la, -al, -l, -a, -lh
            rest_tokens = rest.split()
            clean_args = []
            for arg in rest_tokens:
                if arg.startswith("-") and all(c in "-lahtr1" for c in arg):
                    continue
                clean_args.append(arg.replace("/", "\\"))
            path_arg = " " + " ".join(clean_args) if clean_args else ""
            normalized.append(f"dir{path_arg}")
        elif cname == "which" and rest:
            normalized.append(f"where {rest}")
        elif cname == "clear" and not rest:
            normalized.append("cls")
        else:
            normalized.append(part)
    return "".join(normalized)


class ShellToolSchema(BaseModel):
    command: str = Field(..., description="The shell command to execute.")


class ShellTool(Tool):
    name = "shell"
    description = """\
Executes a system shell command and captures its output.

Use this for:
- Package management & builds: `npm install`, `pip install`, `uv run`, `cargo build`
- Version control: `git status`, `git diff`, `git commit`, `git log`
- Running tests & linters: `pytest`, `ruff check`, `npm test`

CRITICAL RULES:
- For inspecting directory contents: DO NOT use shell commands like `ls` or `dir`. Use the `filesystem` tool (`action="list"`).
- For reading files: DO NOT use shell commands like `cat` or `type`. Use the `filesystem` tool (`action="read"`).
- For searching files or code: Use `search` and `grep` tools.
- For long-running servers or background processes: Use `terminal_session` instead."""
    args_schema = ShellToolSchema

    def run(self, arguments: dict[str, Any]) -> Any:
        try:
            command = arguments.get("command")
            if not command:
                return "Error: No command provided."

            exec_cmd = command
            is_win = platform.system() == "Windows"
            if is_win:
                exec_cmd = normalize_windows_command(command)

            result = subprocess.run(
                exec_cmd,
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

            # Add guidance if a command failed on Windows due to unrecognized command
            if is_win and result.returncode != 0 and result.stderr:
                if "is not recognized as an internal or external command" in result.stderr:
                    output += (
                        "\n[DevOrch Notice: On Windows, use Windows-compatible commands or use the "
                        "'filesystem' tool (action='list' or action='read') instead of shell.]\n"
                    )

            return output if output else f"Command completed with exit code {result.returncode}."

        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 120 seconds."
        except Exception as e:
            return f"Failed to execute command: {str(e)}"
