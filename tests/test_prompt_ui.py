"""Tests for the REPL input surface (key bindings, toolbar, caches)."""

import subprocess

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.shortcuts import prompt as pt_prompt

from cli.prompt_ui import (
    PLACEHOLDER,
    PLACEHOLDER_VARIANTS,
    PROMPT_PREFIX_WIDTH,
    ContextGauge,
    GitBranchCache,
    create_prompt_keybindings,
    next_mode,
    placeholder_for,
    should_clear_screen,
    toolbar_text,
)
from core.modes import AgentMode


def run_prompt(keys: str, on_cycle=None, **kwargs) -> str:
    with create_pipe_input() as inp:
        inp.send_text(keys)
        with create_app_session(input=inp, output=DummyOutput()):
            return pt_prompt(
                "> ",
                key_bindings=create_prompt_keybindings(on_cycle),
                placeholder=[("class:placeholder", PLACEHOLDER)],
                **kwargs,
            )


def test_next_mode_cycles_safest_first():
    assert next_mode(AgentMode.ASK) == AgentMode.AUTO
    assert next_mode(AgentMode.AUTO) == AgentMode.PLAN
    assert next_mode(AgentMode.PLAN) == AgentMode.ASK


def test_enter_submits():
    assert run_prompt("hello\r") == "hello"


def test_ctrl_j_inserts_newline():
    assert run_prompt("a\x0ab\r") == "a\nb"


def test_alt_enter_inserts_newline():
    assert run_prompt("a\x1b\rb\r") == "a\nb"


def test_shift_tab_cycles_mode_without_touching_input():
    calls = []
    out = run_prompt("hi\x1b[Z\r", on_cycle=lambda: calls.append(1))
    assert calls == [1] and out == "hi"


def test_shift_tab_unbound_without_callback():
    assert run_prompt("hi\r") == "hi"


def test_callable_prompt_message_is_supported():
    with create_pipe_input() as inp:
        inp.send_text("x\r")
        with create_app_session(input=inp, output=DummyOutput()):
            out = pt_prompt(lambda: [("class:prompt-mode", "[ASK] ")], placeholder=PLACEHOLDER)
    assert out == "x"


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_git_branch_cached_within_ttl():
    calls, clock = [], FakeClock()

    def fetch():
        calls.append(1)
        return "main"

    cache = GitBranchCache(fetch, ttl=5, clock=clock)
    assert [cache.get() for _ in range(50)] == ["main"] * 50
    assert len(calls) == 1
    clock.t = 4.9
    cache.get()
    assert len(calls) == 1
    clock.t = 5.1
    cache.get()
    assert len(calls) == 2


def test_git_branch_invalidate_and_errors():
    clock = FakeClock()
    seq = iter(["a", subprocess.TimeoutExpired("git", 1), "c"])

    def fetch():
        v = next(seq)
        if isinstance(v, Exception):
            raise v
        return v

    cache = GitBranchCache(fetch, ttl=100, clock=clock)
    assert cache.get() == "a"
    cache.invalidate()
    assert cache.get() is None  # a failing git does not crash the toolbar
    cache.invalidate()
    assert cache.get() == "c"


def test_context_gauge_recomputes_only_on_change():
    calls = []

    def count(history):
        calls.append(1)
        return len(history) * 100

    gauge = ContextGauge(count, limit=1000)
    history = []
    assert gauge.percent(history) == 0
    history.append(object())
    assert gauge.percent(history) == 10
    for _ in range(20):
        gauge.percent(history)
    assert len(calls) == 2
    history.append(object())
    assert gauge.percent(history) == 20


def test_toolbar_text():
    text = toolbar_text(
        cwd="~/proj",
        branch="main",
        provider_model="openai/gpt-4o",
        mode="ask",
        tokens=1234,
        context_pct=42,
        mcp_servers=2,
    )
    assert "~/proj" in text and "git:main" in text and "openai/gpt-4o" in text
    assert "[ASK]" in text and "1,234 tok" in text and "ctx 42%" in text
    assert "MCP: 2" in text and "Shift+Tab" in text


def test_toolbar_omits_empty_parts():
    text = toolbar_text(
        cwd="~", branch=None, provider_model="p/m", mode="auto", tokens=0, context_pct=0
    )
    assert "git:" not in text and "ctx" not in text and "MCP" not in text


# ── width-aware placeholder and toolbar ─────────────────────────────────────

LONG = {
    "cwd": "~/Documents/DevOrch",
    "branch": "feat/boxed-input",
    "provider_model": "mistral/ministral-3b-latest",
    "mode": "ask",
    "tokens": 0,
    "context_pct": 0,
}


@pytest.mark.parametrize("cols", [20, 30, 40, 60, 80, 100, 120, 200])
def test_placeholder_always_fits_on_one_line(cols):
    text = placeholder_for(cols)
    assert PROMPT_PREFIX_WIDTH + len(text) < cols or text == ""


def test_placeholder_picks_the_longest_that_fits():
    assert placeholder_for(200) == PLACEHOLDER_VARIANTS[0]
    assert placeholder_for(80) == PLACEHOLDER_VARIANTS[1]  # the 84-char one wrapped at 80
    assert placeholder_for(40) == PLACEHOLDER_VARIANTS[2]
    assert placeholder_for(10) == ""


@pytest.mark.parametrize("cols", [50, 60, 70, 80, 100, 120])
def test_toolbar_never_wider_than_the_terminal(cols):
    assert len(toolbar_text(**LONG, columns=cols)) <= cols - 1


@pytest.mark.parametrize("cols", [50, 60, 80, 120])
def test_toolbar_keeps_mode_model_and_tokens(cols):
    text = toolbar_text(**LONG, columns=cols)
    assert "[ASK]" in text and "ministral-3b-latest" in text and "0 tok" in text


def test_toolbar_screenshot_case_80_columns():
    # the reported bug: at ~80 columns the mode and token count were clipped off the right edge
    text = toolbar_text(**LONG, columns=80)
    assert "[ASK]" in text and "⚡ 0 tok" in text


def test_toolbar_drops_least_important_first():
    base = {**LONG, "mcp_servers": 2, "tokens": 5000, "cost": 0.3}
    wide = toolbar_text(**base, columns=200)
    assert "Shift+Tab" in wide and "MCP: 2" in wide and "~/Documents/DevOrch" in wide
    mid = toolbar_text(**base, columns=105)
    assert "Shift+Tab" not in mid and "~$0.30" in mid
    tight = toolbar_text(**base, columns=70)
    assert "ctx" in tight and "~$0.30" in tight and "MCP" not in tight
    assert "Documents" not in tight


def test_toolbar_without_columns_is_unchanged():
    assert "Shift+Tab" in toolbar_text(**LONG) and "~/Documents/DevOrch" in toolbar_text(**LONG)


def test_toolbar_hard_clips_as_a_last_resort():
    text = toolbar_text(**LONG, columns=20)
    assert len(text) <= 19 and text.endswith("…")


# ── clearing the screen on start ────────────────────────────────────────────


def test_clear_screen_only_on_a_real_terminal():
    assert should_clear_screen(True, env={})
    assert not should_clear_screen(False, env={})  # piped output / CI must never get escape codes


def test_clear_screen_can_be_disabled_with_env():
    assert not should_clear_screen(True, env={"DEVORCH_NO_CLEAR": "1"})
    assert should_clear_screen(True, env={"DEVORCH_NO_CLEAR": ""})
