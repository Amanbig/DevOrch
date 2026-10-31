"""
Hooks — user-defined shell commands that run around tool execution.

Configured in ``~/.devorch/hooks.yaml`` (global) and ``<project>/.devorch/hooks.yaml``
(project). Project hooks run after global ones.

    hooks:
      PreToolUse:
        - matcher: "shell"          # regex on tool name; omit to match every tool
          command: "./scripts/check.sh"
          timeout: 10               # seconds (default 30)
      PostToolUse:
        - matcher: "edit|filesystem"
          command: "ruff format ."

The hook receives a JSON payload on stdin:
    {"event": "PreToolUse", "tool_name": "...", "tool_input": {...},
     "tool_output": "...",   # PostToolUse only
     "cwd": "..."}

Exit codes:
    0   success (continue)
    2   PreToolUse: block the tool call; stderr is returned to the model as feedback
        PostToolUse: stderr is appended to the tool result as feedback
    other  non-blocking error, logged as a warning
"""

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

PRE_TOOL_USE = "PreToolUse"
POST_TOOL_USE = "PostToolUse"
EVENTS = (PRE_TOOL_USE, POST_TOOL_USE)
DEFAULT_TIMEOUT = 30


@dataclass
class Hook:
    command: str
    matcher: str | None = None
    timeout: int = DEFAULT_TIMEOUT

    def matches(self, tool_name: str) -> bool:
        if not self.matcher:
            return True
        try:
            return re.fullmatch(self.matcher, tool_name) is not None
        except re.error:
            return False


@dataclass
class HookResult:
    blocked: bool = False
    feedback: str = ""


def _load_file(path: Path) -> dict[str, list[Hook]]:
    result: dict[str, list[Hook]] = {}
    if yaml is None or not path.is_file():
        return result
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return result
    for event, entries in (data.get("hooks") or {}).items():
        if event not in EVENTS or not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("command"):
                continue
            try:
                timeout = int(entry.get("timeout", DEFAULT_TIMEOUT))
            except (TypeError, ValueError):
                timeout = DEFAULT_TIMEOUT
            result.setdefault(event, []).append(
                Hook(
                    command=str(entry["command"]),
                    matcher=entry.get("matcher"),
                    timeout=timeout,
                )
            )
    return result


class HookManager:
    def __init__(self, hooks: dict[str, list[Hook]] | None = None, cwd: Path | None = None):
        self.hooks = hooks or {}
        self.cwd = cwd or Path.cwd()

    @classmethod
    def load(cls, cwd: Path | None = None) -> "HookManager":
        cwd = cwd or Path.cwd()
        merged: dict[str, list[Hook]] = {}
        for path in (Path.home() / ".devorch" / "hooks.yaml", cwd / ".devorch" / "hooks.yaml"):
            for event, hooks in _load_file(path).items():
                merged.setdefault(event, []).extend(hooks)
        return cls(merged, cwd)

    def has_hooks(self) -> bool:
        return any(self.hooks.values())

    def run(
        self,
        event: str,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_output: str | None = None,
    ) -> HookResult:
        payload: dict[str, Any] = {
            "event": event,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "cwd": str(self.cwd),
        }
        if tool_output is not None:
            payload["tool_output"] = tool_output
        stdin = json.dumps(payload, default=str)

        feedback: list[str] = []
        for hook in self.hooks.get(event, []):
            if not hook.matches(tool_name):
                continue
            try:
                proc = subprocess.run(
                    hook.command,
                    shell=True,
                    input=stdin,
                    capture_output=True,
                    text=True,
                    timeout=hook.timeout,
                    cwd=self.cwd,
                )
            except subprocess.TimeoutExpired:
                feedback.append(f"hook '{hook.command}' timed out after {hook.timeout}s")
                continue
            except OSError as e:
                feedback.append(f"hook '{hook.command}' failed to start: {e}")
                continue

            if proc.returncode == 2:
                msg = proc.stderr.strip() or f"blocked by hook '{hook.command}'"
                if event == PRE_TOOL_USE:
                    return HookResult(blocked=True, feedback=msg)
                feedback.append(msg)
            elif proc.returncode != 0:
                feedback.append(
                    f"hook '{hook.command}' exited {proc.returncode}: {proc.stderr.strip()}"
                )
        return HookResult(blocked=False, feedback="\n".join(feedback))
