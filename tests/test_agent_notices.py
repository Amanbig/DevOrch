"""The agent's use of the loop safeguard, and its handling of provider placeholder text."""

import pytest

from devorch.core.agent import EMPTY_RESPONSE_TEXT, TOOL_PLACEHOLDER, Agent
from devorch.core.executor import ToolExecutor
from devorch.core.modes import AgentMode, ModeManager
from devorch.core.planner import Planner
from devorch.schemas.message import LLMResponse, Message, ToolCall
from devorch.tools.base import Tool

NOTICE = "Safeguard Notice"


class Echo(Tool):
    name = "echo"
    description = "echo"

    def __init__(self, outputs=None):
        self.outputs = outputs or {}

    def run(self, arguments):
        return self.outputs.get(arguments.get("i"), f"ran {arguments.get('i')}")


class Scripted:
    name = "scripted"
    model = "m"
    supports_images = False
    supports_streaming = False

    def __init__(self, script):
        self.script = list(script)

    def generate(self, messages, tools=None, stream=False):
        return self.script.pop(0)


def calls(*arg_values, content="working"):
    tcs = [ToolCall(name="echo", arguments={"i": v}, id=f"id{n}") for n, v in enumerate(arg_values)]
    return LLMResponse(message=Message(role="assistant", content=content), tool_calls=tcs)


def final(text="done"):
    return LLMResponse(message=Message(role="assistant", content=text))


def make(script, tool=None):
    class P(Planner):
        def plan(self, history):
            return list(history)

    tool = tool or Echo()
    return Agent(
        provider=Scripted(script),
        planner=P(),
        executor=ToolExecutor([tool], require_confirmation=False),
        tools=[tool],
        mode_manager=ModeManager(default_mode=AgentMode.AUTO),
    )


def tool_outputs(agent):
    return [m.content for m in agent.history if m.role == "tool"]


def test_distinct_tool_calls_get_clean_results():
    # regression: every result used to end with "You have already executed this exact command"
    agent = make([calls(1), calls(2), calls(3), final()])
    agent.run("go")
    outs = tool_outputs(agent)
    assert outs == ["ran 1", "ran 2", "ran 3"]
    assert not any(NOTICE in o for o in outs)


def test_a_repeated_call_is_warned_then_blocked():
    agent = make([calls(1), calls(1), calls(1), final()])
    agent.run("go")
    first, second, third = tool_outputs(agent)
    assert first == "ran 1"
    assert second.startswith("ran 1") and NOTICE in second and "already executed" in second
    assert third.startswith("Error: Action blocked by DevOrch safeguard")


def test_error_streak_warning_reaches_the_model():
    errors = {1: "Error: a", 2: "Error: b", 3: "Error: c"}
    agent = make([calls(1), calls(2), calls(3), final()], Echo(errors))
    agent.run("go")
    outs = tool_outputs(agent)
    assert NOTICE not in outs[0] and NOTICE not in outs[1]
    assert "Last 3 tool calls resulted in errors" in outs[2]


def test_blocked_message_with_markup_like_arguments_does_not_crash(monkeypatch):
    import io

    from rich.console import Console

    import devorch.core.agent as agent_mod

    monkeypatch.setattr(agent_mod, "console", Console(file=io.StringIO(), width=200))
    # arguments end up inside the safeguard message
    weird = "[/bold] [red]x"
    tcs = lambda: LLMResponse(  # noqa: E731
        message=Message(role="assistant", content="x"),
        tool_calls=[ToolCall(name="echo", arguments={"i": weird}, id="t")],
    )
    agent = make([tcs(), tcs(), tcs(), final()])
    assert agent.run("go") == "done"
    assert "[/bold]" in tool_outputs(agent)[2]


# ── placeholder text ────────────────────────────────────────────────────────


def test_placeholder_is_not_stored_when_the_model_only_called_tools():
    agent = make([calls(1, content=TOOL_PLACEHOLDER), final()])
    agent.run("go")
    assistant = [m for m in agent.history if m.role == "assistant"]
    assert assistant[0].content == "" and assistant[0].metadata["tool_calls"]
    assert all(TOOL_PLACEHOLDER not in m.content for m in agent.history)


def test_real_text_before_tool_calls_is_kept():
    agent = make([calls(1, content="Let me look at that."), final()])
    agent.run("go")
    assert [m.content for m in agent.history if m.role == "assistant"][0] == "Let me look at that."


@pytest.mark.parametrize("empty", [TOOL_PLACEHOLDER, "", "   "])
def test_an_empty_final_answer_is_explained_not_shown_as_a_tool_call(empty):
    agent = make([final(empty)])
    result = agent.run("go")
    assert result == EMPTY_RESPONSE_TEXT
    assert [m.content for m in agent.history if m.role == "assistant"] == [EMPTY_RESPONSE_TEXT]


def test_normal_final_answers_are_untouched():
    assert make([final("All done.")]).run("go") == "All done."


def test_the_placeholder_constant_matches_what_the_providers_emit():
    import re
    from pathlib import Path

    providers = Path(__file__).resolve().parents[1] / "devorch" / "providers"
    found = set()
    for path in providers.glob("*.py"):
        found |= set(re.findall(r'"(Calling tool[^"]*)"', path.read_text(encoding="utf-8")))
    assert found == {TOOL_PLACEHOLDER}, found
