"""`ask --approvals stdio`: permission questions asked over JSON lines, for editors."""

import io
import json

import pytest
from typer.testing import CliRunner

from devorch.cli.commands import ask as ask_module
from devorch.cli.commands._output import stdio_approver
from devorch.cli.main import app
from devorch.config.permissions import PermissionChoice, PermissionLevel
from devorch.core.executor import ToolExecutor
from devorch.schemas.message import LLMResponse, Message, ToolCall
from devorch.tools.base import Tool
from devorch.utils.logger import get_console

runner = CliRunner()


def reply(*objs):
    return io.StringIO("".join(json.dumps(o) + "\n" for o in objs))


def events(out):
    return [json.loads(line) for line in out.strip().splitlines() if line.startswith("{")]


# ── the approver ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "choice,expected",
    [
        ("once", PermissionChoice.ALLOW_ONCE),
        ("session", PermissionChoice.ALLOW_SESSION),
        ("always", PermissionChoice.ALLOW_ALWAYS),
        ("deny", PermissionChoice.DENY),
        ("surprise", PermissionChoice.DENY),
    ],
)
def test_the_reply_decides(capsys, choice, expected):
    approve = stdio_approver(reply({"id": 1, "choice": choice}))
    assert approve("shell", "rm -r build", "because") == expected
    request = events(capsys.readouterr().out)[0]
    assert request == {
        "type": "permission_request",
        "id": 1,
        "tool": "shell",
        "command": "rm -r build",
        "reason": "because",
    }


def test_closed_stdin_denies(capsys):
    assert stdio_approver(io.StringIO(""))("shell", "x") == PermissionChoice.DENY


def test_noise_and_answers_to_other_requests_are_skipped(capsys):
    stdin = io.StringIO(
        'not json\n{"id": 99, "choice": "once"}\n[1]\n{"id": 1, "choice": "once"}\n'
    )
    assert stdio_approver(stdin)("shell", "x") == PermissionChoice.ALLOW_ONCE


def test_request_ids_count_up(capsys):
    approve = stdio_approver(reply({"id": 1, "choice": "once"}, {"id": 2, "choice": "deny"}))
    assert approve("a", "x") == PermissionChoice.ALLOW_ONCE
    assert approve("b", "y") == PermissionChoice.DENY
    assert [e["id"] for e in events(capsys.readouterr().out)] == [1, 2]


# ── the executor uses it instead of the terminal prompt ─────────────────────


class Touch(Tool):
    name = "touch"
    description = "touch"

    def __init__(self):
        self.ran = []

    def run(self, arguments):
        self.ran.append(arguments)
        return "done"


class AlwaysAsk:
    def check_permission(self, tool_name, command=None):
        return PermissionLevel.ASK, None

    def add_allowed_pattern(self, *a, **k):
        pass


def test_executor_asks_the_approver_and_honours_deny(monkeypatch):
    tool = Touch()
    ex = ToolExecutor([tool], permissions=AlwaysAsk())
    monkeypatch.setattr(
        ex, "_ask_permission", lambda *a, **k: pytest.fail("must not use the terminal prompt")
    )
    seen = []
    ex.approver = lambda t, c, r: seen.append((t, c)) or PermissionChoice.DENY
    assert "denied permission" in ex.execute("touch", {"path": "a"})
    assert tool.ran == [] and seen and seen[0][0] == "touch"

    ex.approver = lambda t, c, r: PermissionChoice.ALLOW_ONCE
    assert ex.execute("touch", {"path": "a"}) == "done" and len(tool.ran) == 1


# ── end to end through `devorch ask` ────────────────────────────────────────


class Scripted:
    name = "fakeprov"
    model = "fake"
    supports_images = False
    supports_streaming = False

    def __init__(self):
        self.step = 0

    def generate(self, messages, tools=None, stream=False):
        self.step += 1
        if self.step == 1:
            call = ToolCall(name="touch", arguments={"path": "a"}, id="c1")
            return LLMResponse(
                message=Message(role="assistant", content="touching"), tool_calls=[call]
            )
        return LLMResponse(message=Message(role="assistant", content="finished"))


@pytest.fixture()
def setup(monkeypatch):
    tool = Touch()
    monkeypatch.setattr(ask_module, "create_provider", lambda *a, **k: Scripted())
    monkeypatch.setattr(ask_module, "build_tools", lambda *a, **k: [tool])
    console = get_console()
    before = console._file
    yield tool
    console._file = before


def run_ask(stdin_lines, *extra):
    return runner.invoke(
        app,
        ["ask", "--output", "stream-json", "--mode", "ask", "--approvals", "stdio", *extra, "go"],
        input="".join(json.dumps(o) + "\n" for o in stdin_lines),
    )


def test_ask_mode_over_stdio_runs_the_tool_after_approval(setup):
    result = run_ask([{"id": 1, "choice": "once"}])
    seq = events(result.stdout)
    assert [e["type"] for e in seq] == ["permission_request", "tool_call", "result"]
    assert seq[0]["tool"] == "touch"
    assert setup.ran == [{"path": "a"}] and seq[-1]["result"] == "finished"


def test_ask_mode_over_stdio_blocks_the_tool_on_deny_or_silence(setup):
    for stdin in ([{"id": 1, "choice": "deny"}], []):
        setup.ran.clear()
        result = run_ask(stdin)
        seq = events(result.stdout)
        assert setup.ran == []
        call = next(e for e in seq if e["type"] == "tool_call")
        assert call["is_error"] and "denied" in call["output"].lower()


def test_approvals_option_is_validated(setup):
    bad = runner.invoke(app, ["ask", "--approvals", "carrier-pigeon", "x"])
    assert bad.exit_code == 2
    needs_stream = runner.invoke(app, ["ask", "--approvals", "stdio", "--output", "json", "x"])
    assert needs_stream.exit_code == 2


# ── a sub-agent does not get more freedom than the agent that spawned it ────


def test_a_sub_agent_inherits_ask_mode_and_the_approver():
    from devorch.core.modes import AgentMode, ModeManager
    from devorch.tools.agent import AgentTool

    tool = Touch()
    parent = ToolExecutor([tool], permissions=AlwaysAsk(), mode_manager=ModeManager(AgentMode.ASK))
    asked = []
    parent.approver = lambda t, c, r: asked.append(t) or PermissionChoice.DENY

    sub = AgentTool(provider=Scripted(), tools=[tool], parent_executor=parent)
    result = sub.run({"task": "touch a file"})
    assert asked == ["touch"]  # the sub-agent's call went to the parent's approver
    assert tool.ran == [] and result  # ...which said no


def test_a_sub_agent_of_an_auto_agent_stays_automatic():
    from devorch.core.modes import AgentMode, ModeManager
    from devorch.tools.agent import AgentTool

    tool = Touch()
    parent = ToolExecutor([tool], permissions=AlwaysAsk(), mode_manager=ModeManager(AgentMode.AUTO))
    parent.approver = lambda *a: pytest.fail("auto mode must not ask")
    AgentTool(provider=Scripted(), tools=[tool], parent_executor=parent).run({"task": "touch"})
    assert len(tool.ran) == 1
