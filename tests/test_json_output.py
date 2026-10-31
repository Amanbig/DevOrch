"""Tests for --output json / stream-json."""

import json

import pytest
import typer

from cli.commands._output import FORMATS, run_with_output, validate_format
from core.context import ContextManager
from schemas.message import TokenUsage


class FakeExecutor:
    def execute(self, tool_name, arguments):
        return "Error: nope" if tool_name == "bad" else "fine"


class FakeAgent:
    def __init__(self, fail=False):
        self.executor = FakeExecutor()
        self.context_manager = ContextManager.__new__(ContextManager)
        from core.context import SessionTokenStats

        self.context_manager.stats = SessionTokenStats()
        self.context_manager.stats.add_turn(
            TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        )
        self.fail = fail

    def run(self, prompt, max_iterations=15):
        if self.fail:
            raise RuntimeError("boom")
        self.executor.execute("shell", {"command": "ls"})
        self.executor.execute("bad", {})
        return f"answer to {prompt}"


def _run(capsys, agent, output):
    code = 0
    try:
        run_with_output(agent, "hi", output=output, provider="p", model="m")
    except typer.Exit as e:
        code = e.exit_code
    return capsys.readouterr().out, code


def test_validate_format(capsys):
    assert validate_format("JSON") == "json"
    assert validate_format("") == "text"
    with pytest.raises(typer.Exit):
        validate_format("xml")
    assert set(FORMATS) == {"text", "json", "stream-json"}


def test_json_success(capsys):
    out, code = _run(capsys, FakeAgent(), "json")
    data = json.loads(out)  # stdout must be exactly one JSON document
    assert code == 0
    assert data["is_error"] is False and data["result"] == "answer to hi"
    assert data["provider"] == "p" and data["model"] == "m"
    assert data["usage"]["total_tokens"] == 15
    assert [c["name"] for c in data["tool_calls"]] == ["shell", "bad"]
    assert data["tool_calls"][1]["is_error"] is True


def test_json_error_exit_code(capsys):
    out, code = _run(capsys, FakeAgent(fail=True), "json")
    data = json.loads(out)
    assert code == 1
    assert data["is_error"] is True and data["error"] == "boom" and data["result"] is None


def test_stream_json_events(capsys):
    out, code = _run(capsys, FakeAgent(), "stream-json")
    events = [json.loads(line) for line in out.strip().splitlines()]
    assert [e["type"] for e in events] == ["tool_call", "tool_call", "result"]
    assert events[0]["name"] == "shell" and events[-1]["is_error"] is False
    assert code == 0


def test_executor_restored(capsys):
    agent = FakeAgent()
    original = agent.executor.execute
    _run(capsys, agent, "json")
    assert agent.executor.execute == original


def test_text_mode_error_does_not_raise(capsys):
    out, code = _run(capsys, FakeAgent(fail=True), "text")
    assert code == 0
