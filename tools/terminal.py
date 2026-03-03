import os
import subprocess
import sys
from typing import Any

from pydantic import BaseModel, Field

from tools.base import Tool


class OpenTerminalSchema(BaseModel):
    command: str = Field(
        ...,
        description=(
            "The command to run in a new terminal window. "
            "Use this for long-running servers (npm run dev, vite, uvicorn, flask run, etc.), "
            "interactive scaffold tools (npm create, npx create-*, ng new, etc.), "
            "or anything else that would block the main session if run normally."
        ),
    )


class OpenTerminalTool(Tool):
    name = "open_terminal"
    description = """\
Opens a new terminal window and runs the given command inside it.

Use this tool whenever you need to:
- Start a development server or daemon (e.g. `npm run dev`, `vite`, `uvicorn app:main`, `flask run`, `next dev`)
- Run an interactive scaffold that prompts the user (e.g. `npm create vite@latest`, `npx create-next-app`, `ng new myapp`)
- Run any long-running process that should NOT block the current session

The main DevOrch session remains fully interactive while the command runs in its own window.
After calling this tool, continue the conversation normally — do NOT wait for the command to finish."""
    args_schema = OpenTerminalSchema

    def run(self, arguments: dict[str, Any]) -> Any:
        command = arguments.get("command", "").strip()
        if not command:
            return "Error: No command provided."

        working_dir = os.getcwd()
        system = sys.platform

        try:
            if system == "win32":
                subprocess.Popen(
                    ["cmd", "/c", "start", "cmd", "/k", command],
                    cwd=working_dir,
                )
                return (
                    f"✓ Opened new terminal window\n\n"
                    f"Command: {command}\n\n"
                    f"The command is now running in a separate window. "
                    f"You can continue the conversation here."
                )

            elif system == "darwin":
                escaped_command = command.replace('"', '\\"')
                escaped_dir = working_dir.replace('"', '\\"')
                subprocess.Popen(
                    [
                        "osascript",
                        "-e",
                        f'tell app "Terminal" to do script "cd \\"{escaped_dir}\\" && {escaped_command}"',
                    ]
                )
                return (
                    f"✓ Opened new Terminal window\n\n"
                    f"Command: {command}\n\n"
                    f"The command is now running in a separate window. "
                    f"You can continue the conversation here."
                )

            else:
                # Linux: try common terminal emulators in order
                terminals = [
                    [
                        "gnome-terminal",
                        "--working-directory",
                        working_dir,
                        "--",
                        "bash",
                        "-c",
                        f"{command}; exec bash",
                    ],
                    ["konsole", "--workdir", working_dir, "-e", f"bash -c '{command}; exec bash'"],
                    ["xterm", "-e", f"bash -c 'cd \"{working_dir}\" && {command}; exec bash'"],
                    [
                        "x-terminal-emulator",
                        "-e",
                        f"bash -c 'cd \"{working_dir}\" && {command}; exec bash'",
                    ],
                ]
                for term_cmd in terminals:
                    try:
                        subprocess.Popen(term_cmd)
                        return (
                            f"✓ Opened new terminal window\n\n"
                            f"Command: {command}\n\n"
                            f"The command is now running in a separate window. "
                            f"You can continue the conversation here."
                        )
                    except FileNotFoundError:
                        continue

                # Fallback: background process
                process = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    cwd=working_dir,
                )
                return (
                    f"✓ Started in background (PID: {process.pid})\n\n"
                    f"Command: {command}\n\n"
                    f"Note: No GUI terminal emulator found — process is running in the background."
                )

        except Exception as e:
            return f"Error opening terminal: {str(e)}\n\nRun manually: {command}"
