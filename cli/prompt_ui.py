"""Input-surface helpers for the REPL: key bindings, toolbar text and small caches.

Kept separate from ``cli/main.py`` so the behaviour can be unit-tested without a terminal.
"""

import shutil
import subprocess
import time
from collections.abc import Callable

from prompt_toolkit.key_binding import KeyBindings

from core.modes import AgentMode
from core.pricing import format_cost

PLACEHOLDER = "Ask anything · @file to attach · / for commands · Alt+Enter or Ctrl+J for a new line"

# Shift+Tab cycles through these (safest first)
MODE_CYCLE = (AgentMode.ASK, AgentMode.AUTO, AgentMode.PLAN)


def next_mode(current: AgentMode) -> AgentMode:
    """The mode Shift+Tab switches to."""
    try:
        return MODE_CYCLE[(MODE_CYCLE.index(current) + 1) % len(MODE_CYCLE)]
    except ValueError:
        return MODE_CYCLE[0]


# Border/label colour per mode, so the mode is visible at a glance (AUTO runs tools unasked)
MODE_BORDER_CLASS = {
    AgentMode.ASK: "class:border-ask",
    AgentMode.AUTO: "class:border-auto",
    AgentMode.PLAN: "class:border-plan",
}


def terminal_columns(default: int = 80) -> int:
    """Current terminal width (prompt_toolkit's view when a prompt is active, else the OS's)."""
    try:
        from prompt_toolkit.application import get_app_or_none

        app = get_app_or_none()
        if app is not None:
            return app.output.get_size().columns
    except Exception:
        pass
    return shutil.get_terminal_size((default, 24)).columns


def prompt_message(mode: AgentMode, columns: int | None = None) -> list[tuple[str, str]]:
    """Two-line prompt: a mode-coloured top border with the mode name, then ``│ > ``.

    A full four-sided box is not possible with a normal prompt (the toolbar is pinned to the bottom
    of the terminal, not under the input), so this is an open box with a left gutter that
    ``prompt_continuation`` extends over multi-line and wrapped input.
    """
    cols = columns if columns is not None else terminal_columns()
    border = MODE_BORDER_CLASS.get(mode, "class:border-ask")
    label = f" {mode.value.upper()} "
    # one column short of the edge so the rule never wraps onto an extra line
    rule = "─" * max(0, cols - 1 - 2 - len(label))
    return [
        (border, "╭─"),
        (f"{border} bold", label),
        (border, rule + "\n"),
        (border, "│ "),
        ("class:prompt-arrow", "> "),
    ]


def prompt_continuation(mode: AgentMode):
    """Factory for prompt_toolkit's ``prompt_continuation``: keep the gutter on every extra line."""
    border = MODE_BORDER_CLASS.get(mode, "class:border-ask")

    def continuation(width: int, line_number: int, wrap_count: int):
        # `width` is the prompt's width (4 for "│ > "); line up under the text after "> "
        return [(border, "│ "), ("", " " * max(0, width - 2))]

    return continuation


def create_prompt_keybindings(on_cycle_mode: Callable[[], None] | None = None) -> KeyBindings:
    """Alt+Enter / Ctrl+J insert a newline (Ctrl+J works in every terminal); Shift+Tab cycles mode."""
    kb = KeyBindings()

    @kb.add("escape", "enter")
    @kb.add("c-j")
    def _newline(event):
        event.current_buffer.insert_text("\n")

    if on_cycle_mode is not None:

        @kb.add("s-tab")
        def _cycle(event):
            on_cycle_mode()
            event.app.invalidate()  # re-render the prompt badge and toolbar

    return kb


class GitBranchCache:
    """Current git branch, refreshed at most every ``ttl`` seconds.

    The bottom toolbar is re-rendered on every keystroke; running ``git`` each time makes typing
    lag in large repositories, so the lookup is cached.
    """

    def __init__(self, fetch: Callable[[], str | None], ttl: float = 5.0, clock=time.monotonic):
        self._fetch = fetch
        self._ttl = ttl
        self._clock = clock
        self._value: str | None = None
        self._at: float | None = None

    def get(self) -> str | None:
        now = self._clock()
        if self._at is None or now - self._at >= self._ttl:
            try:
                self._value = self._fetch()
            except (OSError, subprocess.SubprocessError):
                self._value = None
            self._at = now
        return self._value

    def invalidate(self) -> None:
        self._at = None


class ContextGauge:
    """Context usage as a percentage, recomputed only when the history actually changed."""

    def __init__(self, count: Callable[[list], int], limit: int):
        self._count = count
        self._limit = max(1, limit)
        self._key: tuple | None = None
        self._pct = 0

    def percent(self, history: list) -> int:
        key = (len(history), id(history[-1]) if history else None)
        if key != self._key:
            self._pct = min(999, round(100 * self._count(history) / self._limit))
            self._key = key
        return self._pct


def toolbar_text(
    *,
    cwd: str,
    branch: str | None,
    provider_model: str,
    mode: str,
    tokens: int,
    context_pct: int | None = None,
    cost: float | None = None,
    mcp_servers: int = 0,
) -> str:
    parts = [cwd]
    if branch:
        parts.append(f"git:{branch}")
    parts.append(provider_model)
    parts.append(f"[{mode.upper()}]")
    parts.append(f"⚡ {tokens:,} tok")
    if context_pct is not None and tokens:
        parts.append(f"ctx {context_pct}%")
    if cost is not None and tokens:
        parts.append(f"~{format_cost(cost)}")
    if mcp_servers:
        parts.append(f"MCP: {mcp_servers}")
    parts.append("Shift+Tab: mode")
    return "  " + "     ".join(parts)
