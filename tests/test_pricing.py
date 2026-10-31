"""Tests for cost estimation."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cli.commands._output import run_with_output
from cli.prompt_ui import toolbar_text
from config import settings as settings_mod
from config.settings import Settings, save_config
from core.agent import Agent
from core.executor import ToolExecutor
from core.modes import AgentMode, ModeManager
from core.planner import Planner
from core.pricing import (
    CostTracker,
    Price,
    PriceBook,
    format_cost,
    parse_overrides,
    usage_cost,
)
from schemas.message import LLMResponse, Message, TokenUsage


def u(prompt=0, completion=0, cached=0, written=0):
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        cached_tokens=cached,
        cache_write_tokens=written,
    )


P = Price(input=3.0, output=15.0, cache_read=0.30, cache_write=3.75)


def test_usage_cost_plain():
    # 1M prompt + 1M completion
    assert usage_cost(u(1_000_000, 1_000_000), P) == pytest.approx(18.0)


def test_usage_cost_splits_cached_and_written_out_of_prompt():
    # prompt 1M of which 600k cached, 100k newly cached, 300k fresh
    cost = usage_cost(u(1_000_000, 0, cached=600_000, written=100_000), P)
    assert cost == pytest.approx(0.3 * 3.0 + 0.6 * 0.30 + 0.1 * 3.75)


def test_cache_prices_default_to_input_price():
    p = Price(input=2.0, output=8.0)
    assert usage_cost(u(1_000_000, 0, cached=500_000), p) == pytest.approx(2.0)


def test_cached_larger_than_prompt_is_clamped():
    assert usage_cost(u(100, 0, cached=999), Price(1.0, 1.0)) >= 0


def test_lookup_longest_prefix_and_router_prefix():
    book = PriceBook()
    assert book.lookup("openai", "gpt-4o-mini-2024-07-18").input == 0.15  # not gpt-4o
    assert book.lookup("openai", "gpt-4o-2024-08-06").input == 2.50
    assert book.lookup("openrouter", "anthropic/claude-sonnet-4").input == 3.0
    assert book.lookup("openai", "totally-new-model") is None


def test_local_providers_are_free():
    book = PriceBook()
    for provider in ("local", "lmstudio"):
        price = book.lookup(provider, "whatever")
        assert price == Price(0.0, 0.0)


def test_overrides_take_precedence_and_ignore_garbage():
    overrides = parse_overrides(
        {
            "GPT-4o": {"input": 1.0, "output": 2.0},
            "new-model": {"input": 5, "output": 6, "cache_read": 0.5},
            "broken": {"input": "x"},
            "also-broken": "nope",
        }
    )
    book = PriceBook(overrides)
    assert book.lookup("openai", "gpt-4o").input == 1.0
    assert book.lookup("x", "new-model-v2").cache_read == 0.5
    assert book.lookup("x", "broken") is None
    assert parse_overrides(None) == {} and parse_overrides([1]) == {}


def test_tracker_prices_each_call_at_its_own_model():
    t = CostTracker(PriceBook({"cheap": Price(1.0, 1.0), "dear": Price(10.0, 10.0)}))
    t.add("p", "cheap", u(1_000_000))
    t.add("p", "dear", u(1_000_000))  # user switched models mid-session
    assert t.by_model["p/cheap"].cost == pytest.approx(1.0)
    assert t.by_model["p/dear"].cost == pytest.approx(10.0)
    assert t.total == pytest.approx(11.0) and not t.has_unpriced


def test_tracker_never_guesses_unknown_models():
    t = CostTracker()
    assert t.add("p", "mystery", u(500, 100)) is None
    assert t.total == 0 and t.has_unpriced and not t.has_priced
    entry = t.by_model["p/mystery"]
    assert entry.prompt_tokens == 500 and entry.priced is False


def test_tracker_mixed_and_none_usage():
    t = CostTracker()
    t.add("openai", "gpt-4o", u(1000, 1000))
    t.add("p", "mystery", u(10))
    assert t.add("openai", "gpt-4o", None) is None
    assert t.has_priced and t.has_unpriced and t.total > 0


def test_format_cost():
    assert format_cost(None) == "n/a"
    assert format_cost(0) == "$0.00"
    assert format_cost(0.00421) == "$0.0042"
    assert format_cost(1.234) == "$1.23"
    assert format_cost(1234.5) == "$1,234.50"


# ── integration ─────────────────────────────────────────────────────────────


class UsageProvider:
    name = "openai"
    model = "gpt-4o"
    supports_images = False
    supports_streaming = False

    def generate(self, messages, tools=None, stream=False):
        return LLMResponse(
            message=Message(role="assistant", content="ok"), usage=u(1_000_000, 1_000_000)
        )


def make_agent(provider=None):
    class Pl(Planner):
        def plan(self, history):
            return list(history)

    return Agent(
        provider=provider or UsageProvider(),
        planner=Pl(),
        executor=ToolExecutor([], require_confirmation=False),
        tools=[],
        mode_manager=ModeManager(default_mode=AgentMode.AUTO),
    )


def test_agent_records_cost_per_call():
    agent = make_agent()
    agent.run("hi")
    assert agent.costs.total == pytest.approx(2.50 + 10.0)
    assert agent.last_turn_cost == pytest.approx(12.5)
    agent.run("again")
    assert agent.costs.total == pytest.approx(25.0)


def test_sub_agent_cost_is_shared_with_parent():
    from tools.agent import AgentTool

    agent = make_agent()
    tool = AgentTool(provider=agent.provider, tools=[], costs=agent.costs)
    tool.run({"task": "do a thing"})
    assert agent.costs.total == pytest.approx(12.5)


@pytest.fixture
def json_mode_console(monkeypatch):
    """What `ask --output json` does before running: UI output goes elsewhere, keeping stdout pure.

    A StringIO sink (not sys.stderr): pytest's per-phase capture streams are closed by the time the
    test body runs.
    """
    import io

    from utils.logger import get_console

    monkeypatch.setattr(get_console(), "_file", io.StringIO())


def test_json_output_includes_cost(capsys, json_mode_console):
    agent = make_agent()
    run_with_output(agent, "hi", output="json", provider="openai", model="gpt-4o")
    usage = json.loads(capsys.readouterr().out)["usage"]
    assert usage["cost_usd"] == pytest.approx(12.5) and usage["cost_complete"] is True


def test_json_output_cost_null_for_unpriced_model(capsys, json_mode_console):
    prov = UsageProvider()
    prov.model = "mystery-model"
    agent = make_agent(prov)
    run_with_output(agent, "hi", output="json", provider="openai", model="mystery-model")
    usage = json.loads(capsys.readouterr().out)["usage"]
    assert usage["cost_usd"] is None and usage["cost_complete"] is False


def test_toolbar_shows_cost_only_when_known():
    base = {"cwd": "~", "branch": None, "provider_model": "p/m", "mode": "ask", "tokens": 100}
    assert "~$0.42" in toolbar_text(**base, cost=0.42)
    assert "$" not in toolbar_text(**base, cost=None)
    assert "$" not in toolbar_text(**{**base, "tokens": 0}, cost=0.42)


def test_anthropic_usage_reports_cache_write_tokens():
    from unittest.mock import MagicMock

    from providers.anthropic import AnthropicProvider

    prov = AnthropicProvider(api_key="x")
    prov.client = MagicMock()
    resp = MagicMock()
    resp.content = []
    resp.usage = SimpleNamespace(
        input_tokens=50,
        output_tokens=10,
        cache_read_input_tokens=900,
        cache_creation_input_tokens=100,
    )
    prov.client.messages.create.return_value = resp
    usage = prov.generate([Message(role="user", content="hi")]).usage
    assert usage.cache_write_tokens == 100 and usage.cached_tokens == 900


def test_pricing_survives_save_config(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(settings_mod, "CONFIG_DIR", tmp_path / ".devorch")
    monkeypatch.setattr(settings_mod, "CONFIG_FILE", tmp_path / ".devorch" / "config.yaml")
    monkeypatch.setattr(settings_mod, "KEYRING_AVAILABLE", False)
    (tmp_path / ".devorch").mkdir()
    (tmp_path / ".devorch" / "config.yaml").write_text(
        "pricing:\n  my-model:\n    input: 1.5\n    output: 4.0\n"
    )
    monkeypatch.chdir(tmp_path)
    s = Settings.load()
    assert s.pricing == {"my-model": {"input": 1.5, "output": 4.0}}
    save_config(s)  # e.g. after /model — must not drop the user's prices
    assert "my-model" in (tmp_path / ".devorch" / "config.yaml").read_text()
    assert PriceBook(parse_overrides(Settings.load().pricing)).lookup("x", "my-model").input == 1.5
