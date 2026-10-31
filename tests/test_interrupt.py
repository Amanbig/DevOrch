"""Tests for cancelling a turn with Ctrl+C."""

import json

import pytest
import typer

from cli.commands._output import run_with_output
from core.agent import INTERRUPTED_MESSAGE, INTERRUPTED_NOTE, Agent
from core.executor import ToolExecutor
from core.modes import AgentMode, ModeManager
from core.planner import Planner
from schemas.message import LLMResponse, Message, ToolCall
from tools.base import Tool


class Slow(Tool):
    name = "slow"
    description = "slow"

    def __init__(self, interrupt_on: set[int] | None = None):
        self.calls = 0
        self.interrupt_on = interrupt_on or set()

    def run(self, arguments):
        self.calls += 1
        if self.calls in self.interrupt_on:
            raise KeyboardInterrupt
        return f"done {self.calls}"


class Scripted:
    """Provider returning scripted responses; a response can be an exception class to raise."""

    name = "scripted"
    model = "m"
    supports_images = False
    supports_streaming = False

    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    def generate(self, messages, tools=None, stream=False):
        self.seen.append(list(messages))
        item = self.script.pop(0)
        if isinstance(item, type) and issubclass(item, BaseException):
            raise item
        return item


def tool_resp(*names):
    calls = [ToolCall(name=n, arguments={"i": i}, id=f"id{i}") for i, n in enumerate(names)]
    return LLMResponse(message=Message(role="assistant", content="working"), tool_calls=calls)


def text_resp(text):
    return LLMResponse(message=Message(role="assistant", content=text))


def make_agent(provider, tool):
    class P(Planner):
        def plan(self, history):
            return list(history)

    return Agent(
        provider=provider,
        planner=P(),
        executor=ToolExecutor([tool], require_confirmation=False),
        tools=[tool],
        mode_manager=ModeManager(default_mode=AgentMode.AUTO),
    )


def roles(agent):
    return [m.role for m in agent.history]


def test_interrupt_while_generating_first_response():
    agent = make_agent(Scripted([KeyboardInterrupt]), Slow())
    result = agent.run("do it")
    assert agent.last_run_interrupted and result == INTERRUPTED_MESSAGE
    assert roles(agent) == ["user", "assistant"]
    assert agent.history[-1].content == INTERRUPTED_NOTE


def test_interrupt_during_tool_answers_every_pending_call():
    tool = Slow(interrupt_on={1})
    agent = make_agent(Scripted([tool_resp("slow", "slow")]), tool)
    agent.run("do it")
    assert agent.last_run_interrupted
    assert roles(agent) == ["user", "assistant", "tool", "tool", "assistant"]
    tools = [m for m in agent.history if m.role == "tool"]
    assert [m.tool_call_id for m in tools] == ["id0", "id1"]
    assert all("cancelled" in m.content for m in tools)


def test_interrupt_after_first_tool_of_batch_keeps_real_result():
    tool = Slow(interrupt_on={2})
    agent = make_agent(Scripted([tool_resp("slow", "slow")]), tool)
    agent.run("do it")
    tools = [m for m in agent.history if m.role == "tool"]
    assert tools[0].content.startswith("done 1") and "cancelled" in tools[1].content
    assert [m.tool_call_id for m in tools] == ["id0", "id1"]


def test_interrupt_between_iterations():
    agent = make_agent(Scripted([tool_resp("slow"), KeyboardInterrupt]), Slow())
    agent.run("do it")
    assert roles(agent) == ["user", "assistant", "tool", "assistant"]
    assert agent.history[-1].content == INTERRUPTED_NOTE


def test_next_turn_works_after_interrupt():
    prov = Scripted([KeyboardInterrupt, text_resp("fine")])
    agent = make_agent(prov, Slow())
    agent.run("first")
    assert agent.run("second") == "fine"
    assert not agent.last_run_interrupted
    assert roles(agent) == ["user", "assistant", "user", "assistant"]
    # the second request saw the interrupted turn, still well-formed
    assert [m.role for m in prov.seen[1]] == ["user", "assistant", "user"]


def test_completed_turn_not_flagged():
    agent = make_agent(Scripted([text_resp("hi")]), Slow())
    assert agent.run("q") == "hi" and not agent.last_run_interrupted


def test_flag_resets_each_run():
    agent = make_agent(Scripted([KeyboardInterrupt, text_resp("ok")]), Slow())
    agent.run("a")
    assert agent.last_run_interrupted
    agent.run("b")
    assert not agent.last_run_interrupted


# ── non-interactive commands ────────────────────────────────────────────────


class FakeAgent:
    def __init__(self, interrupted):
        self.executor = ToolExecutor([], require_confirmation=False)
        self.interrupted = interrupted
        self.last_run_interrupted = False
        from core.context import ContextManager

        self.context_manager = ContextManager()

    def run(self, prompt, max_iterations=15, **kw):
        self.last_run_interrupted = self.interrupted
        return "Interrupted..." if self.interrupted else "answer"


def test_text_mode_interrupt_exits_130():
    with pytest.raises(typer.Exit) as exc:
        run_with_output(FakeAgent(True), "p", output="text", provider="p", model="m")
    assert exc.value.exit_code == 130


def test_text_mode_normal_run_does_not_exit():
    run_with_output(FakeAgent(False), "p", output="text", provider="p", model="m")


def test_json_mode_interrupt_reports_error_and_130(capsys):
    with pytest.raises(typer.Exit) as exc:
        run_with_output(FakeAgent(True), "p", output="json", provider="p", model="m")
    data = json.loads(capsys.readouterr().out)
    assert exc.value.exit_code == 130
    assert data["is_error"] is True and data["error"] == "interrupted"


def test_ctrl_c_inside_sub_agent_cancels_parent_turn():
    from tools.agent import AgentTool

    class Interrupting(Scripted):
        """First call (parent) asks for the sub-agent; the sub-agent's call gets Ctrl+C."""

    delegate = LLMResponse(
        message=Message(role="assistant", content="delegating"),
        tool_calls=[ToolCall(name="agent", arguments={"task": "look around"}, id="d1")],
    )
    prov = Interrupting([delegate, KeyboardInterrupt])
    slow = Slow()
    parent_tools: list = [slow]
    agent_tool = AgentTool(provider=prov, tools=parent_tools)
    parent_tools.append(agent_tool)
    agent = make_agent(prov, agent_tool)
    agent.tools = parent_tools
    agent.executor.tools[agent_tool.name] = agent_tool
    agent.run("delegate")
    assert agent.last_run_interrupted
    assert roles(agent)[-1] == "assistant" and agent.history[-1].content == INTERRUPTED_NOTE
    assert prov.script == []  # the sub-agent consumed the interrupt; nothing was left over
    assert len(prov.seen) == 2  # parent call + sub-agent call, and no third (parent) call
