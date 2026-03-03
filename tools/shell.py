import os
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

# Commands that start long-running servers/daemons.
# Note: no trailing spaces — matching is done against each word-token/subcommand.
SERVER_COMMANDS = [
    "npm run dev",
    "npm run serve",
    "npm start",
    "yarn dev",
    "yarn start",
    "pnpm dev",
    "pnpm start",
    "python -m http.server",
    "python -m simplehttpserver",
    "flask run",
    "django runserver",
    "manage.py runserver",
    "uvicorn",
    "gunicorn",
    "node server",
    "nodemon",
    "ng serve",
    "next dev",
    "vite",
    "npx vite",
    "webpack serve",
    "rails server",
    "cargo run",
    "go run",
    "docker-compose up",
    "docker compose up",
]


class ShellToolSchema(BaseModel):
    command: str = Field(..., description="The shell command to execute.")


class ShellTool(Tool):
    name = "shell"
    description = """Executes a shell command on the user's system.

Special handling:
- Interactive commands (like npx create-next-app) run directly in the terminal allowing user interaction
- Server/daemon commands (like npm run dev, python -m http.server) automatically open in a new terminal window, allowing the conversation to continue
- Regular commands are executed and their output is captured"""
    args_schema = ShellToolSchema

    def _is_interactive(self, command: str) -> bool:
        """Check if a command is likely to be interactive."""
        cmd_lower = command.lower()
        for pattern in INTERACTIVE_COMMANDS:
            if pattern in cmd_lower:
                return True
        return False

    def _is_server_command(self, command: str) -> bool:
        """Check if a command (or any part of a chained command) starts a long-running server."""
        # Split on && and ; to check each subcommand independently
        parts = []
        for chunk in command.replace(";", "&&").split("&&"):
            parts.append(chunk.strip().lower())

        for part in parts:
            for pattern in SERVER_COMMANDS:
                # Match if the part equals the pattern, starts with it (space/end), or contains it
                p = pattern.lower()
                if (
                    part == p
                    or part.startswith(p + " ")
                    or part.startswith(p + "\t")
                    or (" " + p + " ") in (" " + part + " ")
                ):
                    return True
        return False

    def _run_in_new_terminal(self, command: str, cwd: str | None = None) -> str:
        """Run a command in a new terminal window."""
        system = sys.platform
        working_dir = cwd or os.getcwd()

        try:
            if system == "win32":
                # Windows: 'start' is a cmd built-in, so we must invoke it via
                # `cmd /c start ...` as a list — using shell=True with a plain
                # string is unreliable for built-in commands.
                subprocess.Popen(
                    ["cmd", "/c", "start", "cmd", "/k", command],
                    cwd=working_dir,
                )
                return (
                    f"✓ Server started in new terminal window\n\n"
                    f"Command: {command}\n\n"
                    f"The server is now running in a separate window. You can continue our conversation here."
                )

            elif system == "darwin":
                # macOS: use osascript to open Terminal
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
                    f"✓ Server started in new Terminal window\n\n"
                    f"Command: {command}\n\n"
                    f"The server is now running in a separate window. You can continue our conversation here."
                )

            else:
                # Linux: try common terminal emulators
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
                            f"✓ Server started in new terminal window\n\n"
                            f"Command: {command}\n\n"
                            f"The server is now running in a separate window. You can continue our conversation here."
                        )
                    except FileNotFoundError:
                        continue

                # Fallback: run in background
                process = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    cwd=working_dir,
                )
                return (
                    f"✓ Server started in background (PID: {process.pid})\n\n"
                    f"Command: {command}\n\n"
                    f"Note: Could not open a new terminal. The server is running in the background."
                )

        except Exception as e:
            return f"Error starting server in new terminal: {str(e)}\n\nTry running the command manually: {command}"

    def run(self, arguments: dict[str, Any]) -> Any:
        try:
            command = arguments.get("command")
            if not command:
                return "Error: No command provided."

            # Check if this is a long-running server command
            if self._is_server_command(command):
                return self._run_in_new_terminal(command)

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
