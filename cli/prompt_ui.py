"""Input-surface helpers for the REPL: key bindings, toolbar text and small caches.

Kept separate from ``cli/main.py`` so the behaviour can be unit-tested without a terminal.
"""

import subprocess
import time
from collections.abc import Callable

from prompt_toolkit.key_binding import KeyBindings

from core.modes import AgentMode

PLACEHOLDER = "Ask anything · @file to attach · / for commands · Alt+Enter or Ctrl+J for a new line"

# Shift+Tab cycles through these (safest first)
MODE_CYCLE = (AgentMode.ASK, AgentMode.AUTO, AgentMode.PLAN)


def next_mode(current: AgentMode) -> AgentMode:
    """The mode Shift+Tab switches to."""
    try:
        return MODE_CYCLE[(MODE_CYCLE.index(current) + 1) % len(MODE_CYCLE)]
    except ValueError:
        return MODE_CYCLE[0]


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
    if mcp_servers:
        parts.append(f"MCP: {mcp_servers}")
    parts.append("Shift+Tab: mode")
    return "  " + "     ".join(parts)
