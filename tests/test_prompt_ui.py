"""Tests for the REPL input surface (key bindings, toolbar, caches)."""

import subprocess

from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.shortcuts import prompt as pt_prompt

from cli.prompt_ui import (
    PLACEHOLDER,
    ContextGauge,
    GitBranchCache,
    create_prompt_keybindings,
    next_mode,
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
