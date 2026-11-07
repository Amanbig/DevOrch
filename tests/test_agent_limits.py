"""Agent integration of model-aware budgets, retries, truncation warnings and --max-turns."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import typer.main
from typer.testing import CliRunner

import devorch.cli.main as cli_main
import devorch.core.agent as agent_mod
from devorch.cli.prompt_ui import ContextGauge
from devorch.config import settings as settings_mod
from devorch.config.settings import Settings, save_config
from devorch.core.agent import Agent
from devorch.core.context import ContextManager
from devorch.core.executor import ToolExecutor
from devorch.core.modes import AgentMode, ModeManager
from devorch.core.planner import Planner
from devorch.providers.base import response_was_truncated
from devorch.schemas.message import LLMResponse, Message, ToolCall
from devorch.tools.base import Tool


class RateLimitError(Exception):
    pass


class AuthenticationError(Exception):
    status_code = 401


class Echo(Tool):
    name = "echo"
    description = "echo"

    def run(self, arguments):
        return f"ran {arguments.get('i')}"


class Provider:
    def __init__(self, script, name="openai", model="gpt-4o", streaming=False):
        self.script = list(script)
        self.name, self.model = name, model
        self.supports_images = False
        self.supports_streaming = streaming
        self.calls = 0

    def generate(self, messages, tools=None, stream=False, on_text=None):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            if on_text and getattr(item, "after_text", None):
                on_text(item.after_text)  # the model had already started answering
            raise item
        if on_text and item.message.content:
            on_text(item.message.content)
        return item


def final(text="done", raw=None):
    return LLMResponse(message=Message(role="assistant", content=text), raw=raw)


def make(provider, **kw):
    class P(Planner):
        def plan(self, history):
            return list(history)

    agent = Agent(
        provider=provider,
        planner=P(),
        executor=ToolExecutor([Echo()], require_confirmation=False),
        tools=[Echo()],
        mode_manager=ModeManager(default_mode=AgentMode.AUTO),
        **kw,
    )
    agent.retry_base_delay = 0.0  # no real waiting in tests
    return agent


@pytest.fixture
def warnings(monkeypatch):
    seen = []
    monkeypatch.setattr(agent_mod, "print_warning", seen.append)
    return seen


# ── history budget follows the model ────────────────────────────────────────


def test_budget_follows_the_model_and_unknown_models_keep_the_old_one():
    assert make(Provider([], model="gpt-4o")).context_manager.compact_threshold_tokens == 64_000
    assert make(Provider([], model="gpt-4")).context_manager.compact_threshold_tokens == int(
        8_192 * 0.6
    )
    assert make(Provider([], model="mystery")).context_manager.compact_threshold_tokens == 16_000


def test_switching_provider_or_model_retunes_the_budget():
    agent = make(Provider([], model="mystery"))
    assert agent.context_manager.compact_threshold_tokens == 16_000
    agent.provider = Provider(
        [], name="anthropic", model="claude-sonnet-4-20250514"
    )  # what /model does
    assert agent.context_manager.compact_threshold_tokens == 64_000
    agent.provider = Provider([], model="gpt-3.5-turbo")
    assert agent.context_manager.compact_threshold_tokens == int(16_385 * 0.6)


def test_a_context_manager_passed_in_keeps_its_own_budget():
    agent = make(
        Provider([], model="gpt-4o"), context_manager=ContextManager(compact_threshold_tokens=1234)
    )
    assert agent.context_manager.compact_threshold_tokens == 1234
    agent.provider = Provider([], model="claude-sonnet-4")
    assert agent.context_manager.compact_threshold_tokens == 1234


def test_config_overrides_apply_and_survive_a_model_switch():
    agent = make(Provider([], model="gpt-4o"))
    agent.set_context_overrides({"gpt-4o": 20_000, "bad": "x"})
    assert agent.context_manager.compact_threshold_tokens == int(20_000 * 0.6)
    agent.provider = Provider([], model="gpt-4o-mini")  # same family -> same override
    assert agent.context_manager.compact_threshold_tokens == int(20_000 * 0.6)
    agent.set_context_overrides(None)
    assert agent.context_manager.compact_threshold_tokens == 64_000


def test_the_context_gauge_follows_the_limit():
    limit = {"v": 1000}
    gauge = ContextGauge(lambda history: 500, lambda: limit["v"])
    history = [object()]
    assert gauge.percent(history) == 50
    limit["v"] = 2000  # a model switch changed the threshold
    assert gauge.percent(history) == 25
    assert ContextGauge(lambda h: 500, 1000).percent(history) == 50  # plain numbers still work


# ── retries ─────────────────────────────────────────────────────────────────


def test_a_rate_limit_is_retried_and_the_turn_still_succeeds(warnings):
    prov = Provider([RateLimitError("slow down"), RateLimitError("slow down"), final("it worked")])
    assert make(prov).run("go") == "it worked"
    assert prov.calls == 3
    assert len(warnings) == 2 and "Retrying in" in warnings[0] and "(1/3)" in warnings[0]


def test_retries_are_bounded(warnings):
    prov = Provider([RateLimitError("x")] * 10)
    agent = make(prov)
    agent.retry_attempts = 2
    with pytest.raises(RateLimitError):
        agent.run("go")
    assert prov.calls == 3 and len(warnings) == 2


def test_auth_errors_are_not_retried(warnings):
    prov = Provider([AuthenticationError("bad key"), final()])
    with pytest.raises(AuthenticationError):
        make(prov).run("go")
    assert prov.calls == 1 and warnings == []


def test_ordinary_bugs_are_not_retried(warnings):
    prov = Provider([ValueError("bug"), final()])
    with pytest.raises(ValueError):
        make(prov).run("go")
    assert prov.calls == 1


def test_nothing_is_retried_after_streamed_text_was_shown(monkeypatch, warnings):
    # retrying would print the start of the answer a second time
    import io

    from rich.console import Console

    monkeypatch.setattr(agent_mod, "console", Console(file=io.StringIO(), width=100))
    err = RateLimitError("dropped mid-answer")
    err.after_text = "Here is the beginning of my answer"
    prov = Provider([err, final("never reached")], streaming=True)
    agent = make(prov)
    agent.stream_output = True
    with pytest.raises(RateLimitError):
        agent.run("go")
    assert prov.calls == 1


def test_a_streaming_failure_before_any_text_is_retried(monkeypatch, warnings):
    import io

    from rich.console import Console

    monkeypatch.setattr(agent_mod, "console", Console(file=io.StringIO(), width=100))
    prov = Provider([RateLimitError("429 at connect"), final("fine")], streaming=True)
    agent = make(prov)
    agent.stream_output = True
    assert agent.run("go") == "fine" and prov.calls == 2


def test_ctrl_c_during_the_retry_wait_cancels_the_turn(monkeypatch):
    # the retry sleep must stay interruptible: a KeyboardInterrupt there is handled like any other
    def interrupted(delay):
        raise KeyboardInterrupt

    monkeypatch.setattr("devorch.core.retry.time.sleep", interrupted)
    prov = Provider([RateLimitError("x"), final("never")])
    agent = make(prov)
    agent.retry_base_delay = 1.0
    agent.run("go")
    assert agent.last_run_interrupted and prov.calls == 1


# ── truncated replies ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (SimpleNamespace(stop_reason="max_tokens"), True),
        (SimpleNamespace(stop_reason="end_turn"), False),
        (SimpleNamespace(choices=[SimpleNamespace(finish_reason="length")]), True),
        (SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop")]), False),
        ({"choices": [{"finish_reason": "length"}]}, True),
        ({"choices": [{"finish_reason": "stop"}]}, False),
        (
            SimpleNamespace(candidates=[SimpleNamespace(finish_reason="FinishReason.MAX_TOKENS")]),
            True,
        ),
        (SimpleNamespace(candidates=[SimpleNamespace(finish_reason="STOP")]), False),
        (None, False),
        ({}, False),
        ({"choices": []}, False),
        (SimpleNamespace(choices=[]), False),
        ("garbage", False),
    ],
)
def test_truncation_detection_across_provider_families(raw, expected):
    assert response_was_truncated(raw) is expected


def test_a_truncated_reply_warns_the_user(warnings):
    cut = final("a long answer that was cut off", raw=SimpleNamespace(stop_reason="max_tokens"))
    assert make(Provider([cut])).run("go") == "a long answer that was cut off"
    assert len(warnings) == 1 and "cut off" in warnings[0]


def test_a_normal_reply_does_not_warn(warnings):
    make(Provider([final("fine", raw=SimpleNamespace(stop_reason="end_turn"))])).run("go")
    assert warnings == []


# ── turn limit ──────────────────────────────────────────────────────────────


def test_the_turn_limit_message_names_the_real_limit():
    def calls(i):
        return LLMResponse(
            message=Message(role="assistant", content="working"),
            tool_calls=[ToolCall(name="echo", arguments={"i": i}, id=f"c{i}")],
        )

    agent = make(Provider([calls(i) for i in range(10)]))
    result = agent.run("go", max_iterations=3)
    assert "(3 iterations)" in result and "15" not in result


# ── settings / CLI ──────────────────────────────────────────────────────────


def test_context_windows_survive_save_config(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(settings_mod, "CONFIG_DIR", tmp_path / ".devorch")
    monkeypatch.setattr(settings_mod, "CONFIG_FILE", tmp_path / ".devorch" / "config.yaml")
    monkeypatch.setattr(settings_mod, "KEYRING_AVAILABLE", False)
    (tmp_path / ".devorch").mkdir()
    (tmp_path / ".devorch" / "config.yaml").write_text("context_windows:\n  my-model: 50000\n")
    monkeypatch.chdir(tmp_path)
    s = Settings.load()
    assert s.context_windows == {"my-model": 50000}
    save_config(s)  # e.g. after /model: must not drop the user's overrides
    assert Settings.load().context_windows == {"my-model": 50000}


def test_max_turns_is_an_option_of_ask_run_and_edit():
    root = typer.main.get_command(cli_main.app)
    for name in ("ask", "run", "edit"):
        opts = {o for p in root.commands[name].params for o in getattr(p, "opts", [])}
        assert "--max-turns" in opts, name


def test_max_turns_is_validated():
    runner = CliRunner()
    for bad in ("0", "-3", "201", "abc"):
        result = runner.invoke(cli_main.app, ["ask", "--max-turns", bad, "hi"])
        assert result.exit_code == 2, bad


def test_max_turns_reaches_the_agent_run(monkeypatch):
    import devorch.cli.commands.ask as ask_mod

    captured = {}
    monkeypatch.setattr(
        ask_mod, "create_provider", lambda *a, **k: SimpleNamespace(name="openai", model="gpt-4o")
    )
    monkeypatch.setattr(ask_mod, "build_tools", lambda *a, **k: [])
    monkeypatch.setattr(ask_mod, "build_agent", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(ask_mod, "run_with_output", lambda agent, prompt, **kw: captured.update(kw))
    runner = CliRunner()
    assert runner.invoke(cli_main.app, ["ask", "--max-turns", "7", "hi"]).exit_code == 0
    assert captured["max_iterations"] == 7
    assert runner.invoke(cli_main.app, ["ask", "hi"]).exit_code == 0
    assert captured["max_iterations"] == 15  # the default is unchanged
