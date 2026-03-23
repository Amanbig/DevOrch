"""
Managed terminal session tool — lets the LLM start long-running processes,
read their output, send input, and stop them, all within the conversation.

Sessions are tracked both in-memory AND persisted to a JSON registry file
so that DevOrch can reconnect to orphaned processes across restarts.
Each session gets a unique name (auto-generated if not provided) and a
persistent log file under ~/.devorch/sessions/.
"""

import json
import os
import random
import signal
import string
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tools.base import Tool

# ── Paths ────────────────────────────────────────────────────────────────────
SESSIONS_DIR = Path.home() / ".devorch" / "sessions"
REGISTRY_FILE = SESSIONS_DIR / "registry.json"

# ── In-memory session registry ──────────────────────────────────────────────
# { session_id: { "process": Popen | None, "log_path": str, "command": str, "pid": int, "cwd": str } }
_SESSIONS: dict[str, dict] = {}
_LOCK = threading.Lock()

# Adjectives and nouns for human-readable unique names
_ADJECTIVES = [
    "swift", "bright", "calm", "dark", "eager", "fast", "green", "happy",
    "iron", "keen", "light", "merry", "noble", "proud", "quick", "red",
    "sharp", "tall", "vivid", "warm", "bold", "cool", "deep", "fine",
]
_NOUNS = [
    "fox", "hawk", "lion", "wolf", "bear", "deer", "dove", "eagle",
    "frog", "goat", "hare", "kite", "lark", "mole", "newt", "owl",
    "pike", "ram", "seal", "toad", "wren", "crow", "lynx", "orca",
]


def _generate_unique_name() -> str:
    """Generate a human-readable unique session name like 'swift-fox-a3f2'."""
    adj = random.choice(_ADJECTIVES)
    noun = random.choice(_NOUNS)
    suffix = "".join(random.choices(string.hexdigits[:16], k=4))
    return f"{adj}-{noun}-{suffix}"


def _ensure_sessions_dir():
    """Create the sessions directory if needed."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _load_registry() -> dict[str, dict]:
    """Load the persistent session registry from disk."""
    if not REGISTRY_FILE.exists():
        return {}
    try:
        with open(REGISTRY_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_registry(registry: dict[str, dict]):
    """Save the session registry to disk."""
    _ensure_sessions_dir()
    with open(REGISTRY_FILE, "w") as f:
        json.dump(registry, f, indent=2)


def _pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _stream_to_file(process: subprocess.Popen, log_path: str) -> None:
    """Background thread: read stdout+stderr and append to log file."""
    try:
        with open(log_path, "ab") as f:
            for line in process.stdout:  # type: ignore[union-attr]
                f.write(line)
                f.flush()
    except Exception:
        pass


def _reconnect_orphaned_sessions():
    """On startup, check the registry for processes that are still alive
    and re-attach them to the in-memory registry."""
    registry = _load_registry()
    cleaned = {}

    for sid, info in registry.items():
        pid = info.get("pid", 0)
        log_path = info.get("log_path", "")

        if pid and _pid_alive(pid):
            # Process still running — register it (without a Popen handle,
            # we can still read its log and send signals)
            with _LOCK:
                if sid not in _SESSIONS:
                    _SESSIONS[sid] = {
                        "process": None,  # No Popen handle for orphans
                        "pid": pid,
                        "log_path": log_path,
                        "command": info.get("command", ""),
                        "cwd": info.get("cwd", ""),
                        "started_at": info.get("started_at", ""),
                    }
            cleaned[sid] = info
        else:
            # Dead process — clean up log file
            if log_path and os.path.exists(log_path):
                try:
                    os.unlink(log_path)
                except OSError:
                    pass

    _save_registry(cleaned)


# Run reconnection on module import
_reconnect_orphaned_sessions()


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
            "'list'  — list all active sessions; "
            "'reconnect' — reconnect to orphaned sessions from previous DevOrch runs."
        ),
    )
    session_id: str | None = Field(
        None,
        description=(
            "Identifier for the session. Required for 'read', 'send', 'stop'. "
            "For 'start', if omitted a unique name is auto-generated. "
            "You can also provide a short descriptive name like 'frontend' or 'api-server'."
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
across multiple conversation turns. Sessions persist across DevOrch restarts.

Actions:
- **start**  — Start a command in a named background session (e.g. `npm run dev`).
               A unique name is auto-generated if you don't provide session_id.
               The process runs in the background; use `read` to see its output.
- **read**   — Read recent stdout/stderr output from a running session.
- **send**   — Send a line of input to the process stdin (e.g. to restart nodemon with `rs\\n`).
- **stop**   — Kill a running session.
- **list**   — Show all currently active sessions and their status.
- **reconnect** — Check for orphaned sessions from previous DevOrch runs.

Sessions are uniquely named (e.g. 'swift-fox-a3f2') and their logs persist
in ~/.devorch/sessions/ so you can reconnect even after restarting DevOrch.

Example workflow:
1. `start` command="npm run dev"              # auto-generates unique name
2. `read`  session_id="swift-fox-a3f2"        # check startup logs
3. `send`  session_id="swift-fox-a3f2" input="rs\\n"  # restart nodemon
4. `stop`  session_id="swift-fox-a3f2"

Use `open_terminal` instead if you want an interactive visible terminal window.
Use this tool when you need programmatic access to a process (check output, send input)."""
    args_schema = TerminalSessionSchema

    # ── helpers ──────────────────────────────────────────────────────────────

    def _get_session(self, session_id: str) -> dict | None:
        with _LOCK:
            return _SESSIONS.get(session_id)

    def _session_alive(self, session: dict) -> bool:
        proc = session.get("process")
        if proc is not None:
            return proc.poll() is None
        # Orphaned session — check PID directly
        pid = session.get("pid", 0)
        return _pid_alive(pid) if pid else False

    def _get_return_code(self, session: dict) -> int | None:
        proc = session.get("process")
        if proc is not None:
            return proc.returncode
        return None

    # ── actions ──────────────────────────────────────────────────────────────

    def _start(self, session_id: str | None, command: str) -> str:
        # Auto-generate unique name if not provided
        if not session_id:
            session_id = _generate_unique_name()
            # Ensure uniqueness
            with _LOCK:
                while session_id in _SESSIONS:
                    session_id = _generate_unique_name()

        with _LOCK:
            if session_id in _SESSIONS:
                existing = _SESSIONS[session_id]
                if self._session_alive(existing):
                    return (
                        f"Error: Session '{session_id}' is already running. "
                        f"Use stop first or choose a different session_id."
                    )
                # Dead session — clean up and restart
                del _SESSIONS[session_id]

        _ensure_sessions_dir()

        # Create a persistent log file (not temp — survives restarts)
        log_path = str(SESSIONS_DIR / f"{session_id}.log")

        cwd = os.getcwd()

        try:
            process = subprocess.Popen(
                command,
                shell=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                bufsize=0,  # unbuffered for real-time output
                preexec_fn=os.setsid,  # new process group for clean kill
            )
        except Exception as e:
            return f"Error starting session '{session_id}': {e}"

        # Background thread streams process output to the log file
        t = threading.Thread(
            target=_stream_to_file,
            args=(process, log_path),
            daemon=True,
            name=f"devorch-session-{session_id}",
        )
        t.start()

        started_at = time.strftime("%Y-%m-%d %H:%M:%S")

        with _LOCK:
            _SESSIONS[session_id] = {
                "process": process,
                "pid": process.pid,
                "log_path": log_path,
                "command": command,
                "cwd": cwd,
                "started_at": started_at,
            }

        # Persist to registry
        registry = _load_registry()
        registry[session_id] = {
            "pid": process.pid,
            "log_path": log_path,
            "command": command,
            "cwd": cwd,
            "started_at": started_at,
        }
        _save_registry(registry)

        return (
            f"Session '{session_id}' started (PID {process.pid})\n\n"
            f"Command: {command}\n"
            f"Working dir: {cwd}\n\n"
            f"Use read action with session_id='{session_id}' to see output.\n"
            f"Use send to send input. Use stop to terminate."
        )

    def _read(self, session_id: str, lines: int) -> str:
        session = self._get_session(session_id)
        if not session:
            return f"Error: No session named '{session_id}'. Use list to see active sessions."

        log_path = session["log_path"]
        alive = self._session_alive(session)
        rc = self._get_return_code(session)
        status = "running" if alive else f"exited (code {rc})" if rc is not None else "exited"

        try:
            if not os.path.exists(log_path):
                return f"[Session '{session_id}' — {status}]\nNo output yet (log file not found)."

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

        process = session.get("process")
        if process is None:
            return (
                f"Error: Session '{session_id}' is an orphaned process (PID {session.get('pid')}). "
                f"Cannot send input to orphaned processes — only read and stop are available."
            )

        if not process.stdin:
            return f"Error: Session '{session_id}' does not have an open stdin pipe."

        try:
            encoded = input_text.encode("utf-8")
            process.stdin.write(encoded)
            process.stdin.flush()
            return f"Sent to '{session_id}': {repr(input_text)}"
        except Exception as e:
            return f"Error sending input to '{session_id}': {e}"

    def _stop(self, session_id: str) -> str:
        session = self._get_session(session_id)
        if not session:
            return f"Error: No session named '{session_id}'."

        if not self._session_alive(session):
            with _LOCK:
                _SESSIONS.pop(session_id, None)
            # Remove from registry
            registry = _load_registry()
            registry.pop(session_id, None)
            _save_registry(registry)
            return f"Session '{session_id}' was already stopped."

        process = session.get("process")
        pid = session.get("pid", 0)

        try:
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            elif pid:
                # Orphaned process — send signal directly
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except (OSError, ProcessLookupError):
                        pass

            with _LOCK:
                _SESSIONS.pop(session_id, None)

            # Remove from registry (but keep log file for reference)
            registry = _load_registry()
            registry.pop(session_id, None)
            _save_registry(registry)

            return f"Session '{session_id}' stopped."

        except Exception as e:
            return f"Error stopping session '{session_id}': {e}"

    def _list(self) -> str:
        # Also check for any orphaned sessions we haven't loaded yet
        _reconnect_orphaned_sessions()

        with _LOCK:
            sessions = dict(_SESSIONS)

        if not sessions:
            return "No active sessions."

        lines = ["Active sessions:\n"]
        for sid, s in sessions.items():
            alive = self._session_alive(s)
            rc = self._get_return_code(s)
            status = "running" if alive else f"exited ({rc})" if rc is not None else "exited"
            icon = "●" if alive else "✗"
            orphan = " (orphaned)" if s.get("process") is None and alive else ""
            started = s.get("started_at", "")
            lines.append(
                f"  {sid:25s} {icon} {status:15s} {orphan}"
                f"\n    cmd: {s['command']}"
                f"\n    pid: {s.get('pid', '?')}  started: {started}"
                f"\n    cwd: {s.get('cwd', '?')}\n"
            )

        return "\n".join(lines)

    def _reconnect(self) -> str:
        """Force reconnection to orphaned sessions."""
        _reconnect_orphaned_sessions()
        with _LOCK:
            sessions = dict(_SESSIONS)

        if not sessions:
            return "No sessions found (active or orphaned)."

        alive_count = sum(1 for s in sessions.values() if self._session_alive(s))
        return (
            f"Reconnected. Found {len(sessions)} session(s), {alive_count} still running.\n"
            f"Use 'list' to see details."
        )

    # ── dispatch ─────────────────────────────────────────────────────────────

    def run(self, arguments: dict[str, Any]) -> Any:
        action = (arguments.get("action") or "").lower().strip()
        session_id = (arguments.get("session_id") or "").strip() or None
        command = arguments.get("command", "")
        input_text = arguments.get("input", "")
        lines = int(arguments.get("lines") or 50)

        if action == "list":
            return self._list()

        if action == "reconnect":
            return self._reconnect()

        if action == "start":
            if not command:
                return "Error: command is required for 'start'."
            return self._start(session_id, command)

        if not session_id:
            return "Error: session_id is required for this action."

        if action == "read":
            return self._read(session_id, lines)

        elif action == "send":
            if input_text is None:
                return "Error: input is required for 'send'."
            return self._send(session_id, input_text)

        elif action == "stop":
            return self._stop(session_id)

        else:
            return (
                f"Error: Unknown action '{action}'. "
                f"Valid actions: start, read, send, stop, list, reconnect."
            )
