"""
File checkpoints — snapshot files before the agent modifies them so a turn can be undone.

Only files changed through the built-in ``edit`` and ``filesystem`` (write) tools are tracked.
Changes made via ``shell`` commands are not captured.

Each user turn gets a turn number (``begin_turn``). The first time a file is about to change
within a turn, its original content (or "did not exist") is recorded. ``rewind_turn`` restores
every file touched in the most recent turn.
"""

import os
from dataclasses import dataclass, field
from typing import Any

MAX_FILE_BYTES = 5 * 1024 * 1024  # skip snapshotting files larger than this


@dataclass
class Checkpoint:
    turn: int
    label: str
    # path -> original bytes, or None if the file did not exist
    files: dict[str, bytes | None] = field(default_factory=dict)


def tracked_path(tool_name: str, arguments: dict[str, Any]) -> str | None:
    """Return the path a tool call is about to modify, or None if it's read-only."""
    path = arguments.get("path")
    if not path:
        return None
    if tool_name == "filesystem" and arguments.get("action") == "write":
        return path
    if tool_name == "edit" and not arguments.get("dry_run", False):
        return path
    return None


class CheckpointManager:
    def __init__(self) -> None:
        self.turn = 0
        self._label = ""
        self.checkpoints: list[Checkpoint] = []

    def begin_turn(self, label: str = "") -> None:
        self.turn += 1
        self._label = label.strip().splitlines()[0][:60] if label.strip() else ""

    def _current(self) -> Checkpoint:
        if self.checkpoints and self.checkpoints[-1].turn == self.turn:
            return self.checkpoints[-1]
        cp = Checkpoint(turn=self.turn, label=self._label)
        self.checkpoints.append(cp)
        return cp

    def snapshot(self, path: str) -> bool:
        """Record the current state of ``path`` once per turn. Returns True if recorded."""
        full = os.path.abspath(path)
        cp = self._current()
        if full in cp.files:
            return False
        try:
            if os.path.isfile(full):
                if os.path.getsize(full) > MAX_FILE_BYTES:
                    return False
                with open(full, "rb") as f:
                    cp.files[full] = f.read()
            elif os.path.exists(full):
                return False  # directory or special file
            else:
                cp.files[full] = None
        except OSError:
            return False
        return True

    def before_tool(self, tool_name: str, arguments: dict[str, Any]) -> None:
        path = tracked_path(tool_name, arguments)
        if path:
            self.snapshot(path)

    def rewind_turn(self) -> list[str]:
        """Restore files changed in the latest turn. Returns descriptions of what was done."""
        actions: list[str] = []
        while self.checkpoints and self.checkpoints[-1].turn == self.turn:
            cp = self.checkpoints.pop()
            for path, original in cp.files.items():
                try:
                    if original is None:
                        if os.path.exists(path):
                            os.remove(path)
                            actions.append(f"deleted {path}")
                    else:
                        os.makedirs(os.path.dirname(path), exist_ok=True)
                        with open(path, "wb") as f:
                            f.write(original)
                        actions.append(f"restored {path}")
                except OSError as e:
                    actions.append(f"failed {path}: {e}")
        self.turn = max(0, self.turn - 1)
        return actions

    def summary(self) -> list[tuple[int, str, list[str]]]:
        return [(cp.turn, cp.label, sorted(cp.files)) for cp in self.checkpoints]
