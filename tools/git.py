"""
Git Tool — structured, safe git operations.

Unlike running ``git`` through the shell, this tool:
  - never goes through a shell (arguments are passed as a list, so messages/paths can't inject)
  - rejects ref and path values that look like options (``--force``, ``-D``…)
  - exposes only non-destructive actions (no push, reset, clean, force or rebase)
  - reports a clear permission description (``git status``, ``git commit <msg>``) so read-only
    actions can be allowed by default while ``add``/``commit``/``branch create``/``switch`` ask.
"""

import subprocess
from typing import Any, Literal

from pydantic import BaseModel, Field

from tools.base import Tool

MAX_OUTPUT_CHARS = 20_000
TIMEOUT_SECONDS = 60


class GitToolSchema(BaseModel):
    action: Literal[
        "status", "diff", "log", "show", "branch_list", "branch_create", "switch", "add", "commit"
    ] = Field(..., description="Git action to perform.")
    paths: list[str] = Field(
        default_factory=list, description="File paths (diff, log, add). Use ['.'] with add for all."
    )
    ref: str = Field(
        default="", description="Commit/branch/range (show, diff, log, switch), or new branch name."
    )
    message: str = Field(default="", description="Commit message (commit).")
    staged: bool = Field(default=False, description="diff: show staged changes instead.")
    max_count: int = Field(default=20, description="log: number of commits (max 200).")


def describe(arguments: dict[str, Any]) -> str:
    """Permission-matching description for a git tool call."""
    action = arguments.get("action", "")
    if action == "branch_list":
        return "git branch list"
    if action == "branch_create":
        return f"git branch create {arguments.get('ref', '')}"
    if action == "switch":
        return f"git switch {arguments.get('ref', '')}"
    if action == "add":
        return f"git add {' '.join(arguments.get('paths') or [])}"
    if action == "commit":
        return f"git commit {arguments.get('message', '')}"
    return f"git {action}"


class GitTool(Tool):
    name = "git"
    description = """\
Structured git operations in the current repository. Prefer this over `shell` for git.

Actions:
- status: working tree status (branch + short status)
- diff: unstaged changes (staged=true for staged); optional ref and paths
- log: recent commits (max_count, optional paths)
- show: a commit (ref, default HEAD)
- branch_list: list local branches
- branch_create: create a branch named `ref` (does not switch)
- switch: switch to branch `ref`
- add: stage `paths`
- commit: commit staged changes with `message`

Destructive operations (push, reset, clean, rebase, force) are intentionally unavailable;
ask the user to run those themselves."""
    args_schema = GitToolSchema

    def __init__(self, cwd: str | None = None):
        self.cwd = cwd

    # ── helpers ──────────────────────────────────────────────────────────

    def _git(self, *args: str) -> tuple[int, str]:
        try:
            proc = subprocess.run(
                ["git", *args],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                cwd=self.cwd,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError:
            return 127, "Error: git is not installed or not on PATH."
        except subprocess.TimeoutExpired:
            return 124, f"Error: git timed out after {TIMEOUT_SECONDS}s."
        out = (proc.stdout or "") + (proc.stderr or "")
        if len(out) > MAX_OUTPUT_CHARS:
            out = out[:MAX_OUTPUT_CHARS] + "\n... [truncated]"
        return proc.returncode, out.strip()

    @staticmethod
    def _bad_value(value: str) -> bool:
        return value.startswith("-") or "\x00" in value

    def _result(self, code: int, out: str, empty: str = "(no output)") -> str:
        if code != 0:
            return f"Error: git exited {code}: {out}" if not out.startswith("Error") else out
        return out or empty

    # ── actions ──────────────────────────────────────────────────────────

    def run(self, arguments: dict[str, Any]) -> Any:
        action = arguments.get("action")
        paths: list[str] = list(arguments.get("paths") or [])
        ref: str = arguments.get("ref") or ""
        message: str = arguments.get("message") or ""

        for value in [ref, *paths]:
            if self._bad_value(value):
                return f"Error: refusing option-like or invalid value: {value!r}"

        if action == "status":
            return self._result(*self._git("status", "--short", "--branch"))

        if action == "diff":
            args = ["diff"]
            if arguments.get("staged"):
                args.append("--staged")
            if ref:
                args.append(ref)
            if paths:
                args += ["--", *paths]
            return self._result(*self._git(*args), empty="(no changes)")

        if action == "log":
            count = max(1, min(int(arguments.get("max_count") or 20), 200))
            args = ["log", f"--max-count={count}", "--oneline", "--decorate"]
            if ref:
                args.append(ref)
            if paths:
                args += ["--", *paths]
            return self._result(*self._git(*args), empty="(no commits)")

        if action == "show":
            return self._result(*self._git("show", "--stat", "--patch", ref or "HEAD"))

        if action == "branch_list":
            return self._result(*self._git("branch", "--list", "--verbose"))

        if action == "branch_create":
            if not ref:
                return "Error: 'ref' (new branch name) is required."
            code, out = self._git("check-ref-format", "--branch", ref)
            if code != 0:
                return f"Error: invalid branch name {ref!r}"
            return self._result(*self._git("branch", ref), empty=f"Created branch {ref}")

        if action == "switch":
            if not ref:
                return "Error: 'ref' (branch name) is required."
            return self._result(*self._git("switch", ref))

        if action == "add":
            if not paths:
                return "Error: 'paths' is required (use ['.'] to stage everything)."
            return self._result(
                *self._git("add", "--", *paths), empty=f"Staged {len(paths)} path(s)"
            )

        if action == "commit":
            if not message.strip():
                return "Error: 'message' is required."
            return self._result(*self._git("commit", "-m", message))

        return f"Error: unknown action {action!r}."
