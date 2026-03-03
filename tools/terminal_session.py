"""
Managed terminal session tool — lets the LLM start long-running processes,
read their output, send input, and stop them, all within the conversation.

Session data is stored as a simple in-process dict (sessions survive for the
lifetime of one DevPilot run). Each session gets a temp log file so the LLM
can poll output without blocking.
"""

import os
import subprocess
import sys
import tempfile
import threading
from typing import Any

from pydantic import BaseModel, Field

from tools.base import Tool

# ── In-memory session registry ──────────────────────────────────────────────
# { session_id: { "process": Popen, "log_file": str, "command": str } }
_SESSIONS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _stream_to_file(process: subprocess.Popen, log_path: str) -> None:
    """Background thread: read stdout+stderr and append to log file."""
    try:
        with open(log_path, "ab") as f:
            for line in process.stdout:  # type: ignore[union-attr]
                f.write(line)
                f.flush()
    except Exception:
        pass


# ── Schema ───────────────────────────────────────────────────────────────────


class TerminalSessionSchema(BaseModel):
    action: str = Field(
        ...,
        description=(
            "Action to perform. One of: "
            "'start' — launch a command in a managed background session; "
            "'read'  — get recent output from a running session; "
            "'send'  — send a line of text/input to a running session's stdin; "
            "'stop'  — terminate a session; "
            "'list'  — list all active sessions."
        ),
    )
    session_id: str | None = Field(
        None,
        description=(
            "Identifier for the session. Required for 'start', 'read', 'send', 'stop'. "
            "Choose a short, descriptive name, e.g. 'frontend', 'api-server', 'worker'."
        ),
    )
    command: str | None = Field(
        None,
        description="Shell command to run. Required for 'start'.",
    )
    input: str | None = Field(
        None,
        description=(
            "Text to send to the process stdin. Required for 'send'. "
            "Include a newline (\\n) if the program expects Enter to be pressed."
        ),
    )
    lines: int = Field(
        50,
        description="Number of recent output lines to return for 'read'. Default 50.",
    )


# ── Tool ──────────────────────────────────────────────────────────────────────


class TerminalSessionTool(Tool):
    name = "terminal_session"
    description = """\
Manages long-running background terminal sessions so you can interact with them
across multiple conversation turns.

Actions:
- **start**  — Start a command in a named background session (e.g. `npm run dev`).
               The process runs in the background; use `read` to see its output.
- **read**   — Read recent stdout/stderr output from a running session.
- **send**   — Send a line of input to the process stdin (e.g. to restart nodemon with `rs\\n`).
- **stop**   — Kill a running session.
- **list**   — Show all currently active sessions and their status.

Example workflow:
1. `start` session_id="server" command="npm run dev"
2. `read`  session_id="server"          # check startup logs
3. `send`  session_id="server" input="rs\\n"  # restart nodemon
4. `stop`  session_id="server"

Use `open_terminal` instead if you want an interactive visible terminal window.
Use this tool when you need programmatic access to a process (check output, send input)."""
    args_schema = TerminalSessionSchema

    # ── helpers ──────────────────────────────────────────────────────────────

    def _get_session(self, session_id: str) -> dict | None:
        with _LOCK:
            return _SESSIONS.get(session_id)

    def _session_alive(self, session: dict) -> bool:
        return session["process"].poll() is None

    # ── actions ──────────────────────────────────────────────────────────────

    def _start(self, session_id: str, command: str) -> str:
        with _LOCK:
            if session_id in _SESSIONS:
                existing = _SESSIONS[session_id]
                if existing["process"].poll() is None:
                    return (
                        f"Error: Session '{session_id}' is already running. "
                        f"Use stop first or choose a different session_id."
                    )
                # Dead session — clean up and restart
                del _SESSIONS[session_id]

        # Create a temp log file for stdout+stderr
        log_fd, log_path = tempfile.mkstemp(prefix=f"devpilot_{session_id}_", suffix=".log")
        os.close(log_fd)

        try:
            process = subprocess.Popen(
                command,
                shell=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=os.getcwd(),
                bufsize=0,  # unbuffered for real-time output
            )
        except Exception as e:
            os.unlink(log_path)
            return f"Error starting session '{session_id}': {e}"

        # Background thread streams process output to the log file
        t = threading.Thread(
            target=_stream_to_file,
            args=(process, log_path),
            daemon=True,
            name=f"devpilot-session-{session_id}",
        )
        t.start()

        with _LOCK:
            _SESSIONS[session_id] = {
                "process": process,
                "log_path": log_path,
                "command": command,
            }

        return (
            f"✓ Session '{session_id}' started (PID {process.pid})\n\n"
            f"Command: {command}\n\n"
            f"Use read action to see output. Use send to send input. Use stop to terminate."
        )

    def _read(self, session_id: str, lines: int) -> str:
        session = self._get_session(session_id)
        if not session:
            return f"Error: No session named '{session_id}'. Use list to see active sessions."

        log_path = session["log_path"]
        alive = self._session_alive(session)
        status = "running" if alive else f"exited (code {session['process'].returncode})"

        try:
            with open(log_path, "rb") as f:
                content = f.read()

            text = content.decode("utf-8", errors="replace")
            output_lines = text.splitlines()

            if not output_lines:
                return f"[Session '{session_id}' — {status}]\nNo output yet."

            tail = output_lines[-lines:]
            skipped = max(0, len(output_lines) - lines)
            prefix = f"[... {skipped} earlier lines omitted ...]\n" if skipped else ""

            return f"[Session '{session_id}' — {status}]\n\n{prefix}" + "\n".join(tail)

        except Exception as e:
            return f"Error reading session '{session_id}' output: {e}"

    def _send(self, session_id: str, input_text: str) -> str:
        session = self._get_session(session_id)
        if not session:
            return f"Error: No session named '{session_id}'."

        if not self._session_alive(session):
            return f"Error: Session '{session_id}' is no longer running."

        process = session["process"]
        if not process.stdin:
            return f"Error: Session '{session_id}' does not have an open stdin pipe."

        try:
            encoded = input_text.encode("utf-8")
            process.stdin.write(encoded)
            process.stdin.flush()
            return f"✓ Sent to '{session_id}': {repr(input_text)}"
        except Exception as e:
            return f"Error sending input to '{session_id}': {e}"

    def _stop(self, session_id: str) -> str:
        session = self._get_session(session_id)
        if not session:
            return f"Error: No session named '{session_id}'."

        process = session["process"]
        if not self._session_alive(session):
            with _LOCK:
                _SESSIONS.pop(session_id, None)
            return f"Session '{session_id}' was already stopped."

        try:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

            # Clean up log file
            log_path = session.get("log_path", "")
            try:
                if log_path and os.path.exists(log_path):
                    os.unlink(log_path)
            except Exception:
                pass

            with _LOCK:
                _SESSIONS.pop(session_id, None)

            return f"✓ Session '{session_id}' stopped."

        except Exception as e:
            return f"Error stopping session '{session_id}': {e}"

    def _list(self) -> str:
        with _LOCK:
            sessions = dict(_SESSIONS)

        if not sessions:
            return "No active sessions."

        lines = ["Active sessions:\n"]
        for sid, s in sessions.items():
            alive = s["process"].poll() is None
            status = "● running" if alive else f"✗ exited ({s['process'].returncode})"
            lines.append(f"  {sid:20s} {status:20s}  {s['command']}")

        return "\n".join(lines)

    # ── dispatch ─────────────────────────────────────────────────────────────

    def run(self, arguments: dict[str, Any]) -> Any:
        action = (arguments.get("action") or "").lower().strip()
        session_id = (arguments.get("session_id") or "").strip()
        command = arguments.get("command", "")
        input_text = arguments.get("input", "")
        lines = int(arguments.get("lines") or 50)

        if action == "list":
            return self._list()

        if not session_id:
            return "Error: session_id is required for this action."

        if action == "start":
            if not command:
                return "Error: command is required for 'start'."
            return self._start(session_id, command)

        elif action == "read":
            return self._read(session_id, lines)

        elif action == "send":
            if input_text is None:
                return "Error: input is required for 'send'."
            return self._send(session_id, input_text)

        elif action == "stop":
            return self._stop(session_id)

        else:
            return (
                f"Error: Unknown action '{action}'. Valid actions: start, read, send, stop, list."
            )
