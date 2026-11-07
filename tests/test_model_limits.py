"""Context budgets and output limits per model."""

from unittest.mock import MagicMock

import pytest

from devorch.core.context import ContextManager
from devorch.core.model_limits import (
    ANTHROPIC_DEFAULT_OUTPUT,
    COMPACT_CAP,
    DEFAULT_COMPACT_THRESHOLD,
    MIN_COMPACT_THRESHOLD,
    ModelLimits,
    anthropic_max_output,
    parse_overrides,
)
from devorch.providers.anthropic import AnthropicProvider
from devorch.schemas.message import Message

L = ModelLimits()


@pytest.mark.parametrize(
    ("model", "window"),
    [
        ("gpt-4o", 128_000),
        ("gpt-4o-mini-2024-07-18", 128_000),
        ("gpt-4-turbo", 128_000),
        ("gpt-4", 8_192),  # not mistaken for gpt-4o / gpt-4-turbo
        ("gpt-4-32k", 32_768),
        ("gpt-4.1-mini", 1_000_000),
        ("gpt-3.5-turbo", 16_385),
        ("o1-preview", 200_000),
        ("claude-sonnet-4-20250514", 200_000),
        ("claude-3-haiku-20240307", 200_000),
        ("gemini-1.5-pro", 1_000_000),
        ("gemini-2.0-flash", 1_000_000),
        ("deepseek-chat", 64_000),
        ("mistral-large-latest", 128_000),
        ("ministral-3b-latest", 128_000),
        ("moonshot-v1-8k", 8_192),
        ("moonshot-v1-128k", 131_072),
        ("llama-3.1-70b-versatile", 128_000),
    ],
)
def test_known_context_windows(model, window):
    assert L.context_window("openai", model) == window


def test_router_prefixes_are_ignored():
    assert L.context_window("openrouter", "anthropic/claude-sonnet-4") == 200_000
    assert L.context_window("openrouter", "openai/gpt-4o") == 128_000


def test_unknown_models_have_no_window_and_keep_the_old_budget():
    assert L.context_window("openai", "brand-new-model") is None
    assert L.compact_threshold("openai", "brand-new-model") == DEFAULT_COMPACT_THRESHOLD == 16_000


@pytest.mark.parametrize("provider", ["local", "lmstudio", "custom"])
def test_server_controlled_providers_are_treated_as_unknown(provider):
    # an Ollama/LM Studio server sets its own context size whatever the model supports
    assert L.context_window(provider, "llama-3.1-8b") is None
    assert L.compact_threshold(provider, "llama-3.1-8b") == DEFAULT_COMPACT_THRESHOLD


def test_compaction_threshold_scales_with_the_window_but_is_capped():
    assert L.compact_threshold("openai", "gpt-4o") == COMPACT_CAP == 64_000  # 60% would be 76,800
    assert L.compact_threshold("anthropic", "claude-sonnet-4") == COMPACT_CAP
    assert L.compact_threshold("gemini", "gemini-2.0-flash") == COMPACT_CAP
    assert L.compact_threshold("openai", "gpt-3.5-turbo") == int(16_385 * 0.6)
    assert L.compact_threshold("openai", "gpt-4") == int(
        8_192 * 0.6
    )  # never later than 60% of the window


def test_a_tiny_window_still_gets_a_usable_floor():
    assert ModelLimits({"toy": 2_000}).compact_threshold("x", "toy") == MIN_COMPACT_THRESHOLD


def test_the_threshold_is_always_inside_the_window():
    for model in ("gpt-4", "gpt-3.5-turbo", "gpt-4o", "claude-opus-4", "moonshot-v1-8k"):
        window = L.context_window("openai", model)
        assert L.compact_threshold("openai", model) < window


def test_overrides_win_even_for_local_servers():
    limits = ModelLimits(parse_overrides({"My-Model": 50_000, "llama3": 4096}))
    assert limits.context_window("openai", "my-model-v2") == 50_000
    assert limits.context_window("local", "llama3") == 4096  # the user knows their server's num_ctx
    assert limits.compact_threshold("local", "llama3") == max(
        MIN_COMPACT_THRESHOLD, int(4096 * 0.6)
    )
    assert limits.context_window("openai", "gpt-4o") == 128_000  # others unaffected


def test_override_parsing_ignores_garbage():
    assert parse_overrides({"a": "100000", "b": "lots", "c": -5, "d": 0, "e": None}) == {
        "a": 100000
    }
    assert parse_overrides(None) == {} and parse_overrides([1, 2]) == {}


def test_context_manager_follows_the_model():
    cm = ContextManager()
    assert cm.compact_threshold_tokens == 16_000  # unchanged default
    assert cm.configure_for("anthropic", "claude-sonnet-4") == 64_000
    assert cm.compact_threshold_tokens == 64_000
    cm.configure_for("openai", "gpt-4")
    assert cm.compact_threshold_tokens == int(8_192 * 0.6)


# ── Anthropic output limits ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("model", "streaming", "expected"),
    [
        ("claude-opus-4-20250514", True, 32_000),
        ("claude-opus-4-20250514", False, 16_000),  # the SDK refuses big non-streaming requests
        ("claude-sonnet-4-20250514", True, 64_000),
        ("claude-sonnet-4-20250514", False, 16_000),
        ("claude-3-7-sonnet", True, 64_000),
        ("claude-3-5-sonnet-20241022", True, 8_192),
        ("claude-3-5-haiku-20241022", False, 8_192),
        ("claude-3-haiku-20240307", True, 4_096),  # older models would 400 above this
        ("claude-3-opus-20240229", False, 4_096),
        ("claude-future-model", True, ANTHROPIC_DEFAULT_OUTPUT),
        ("anthropic/claude-sonnet-4", True, 64_000),
    ],
)
def test_anthropic_max_output(model, streaming, expected):
    assert anthropic_max_output(model, streaming) == expected


def _anthropic(model):
    prov = AnthropicProvider(model=model, api_key="x")
    prov.client = MagicMock()
    resp = MagicMock()
    resp.content = []
    resp.usage = None
    prov.client.messages.create.return_value = resp
    return prov


def test_anthropic_requests_the_model_limit_not_4096():
    prov = _anthropic("claude-sonnet-4-20250514")
    prov.generate([Message(role="user", content="hi")])
    assert prov.client.messages.create.call_args.kwargs["max_tokens"] == 16_000


def test_anthropic_streaming_requests_the_full_limit():
    from types import SimpleNamespace

    prov = _anthropic("claude-sonnet-4-20250514")
    final = MagicMock()
    final.content = [SimpleNamespace(type="text", text="x")]
    final.usage = None
    ctx = MagicMock()
    ctx.__enter__.return_value.text_stream = iter(["x"])
    ctx.__enter__.return_value.get_final_message.return_value = final
    prov.client.messages.stream.return_value = ctx
    prov.generate([Message(role="user", content="hi")], on_text=lambda t: None)
    assert prov.client.messages.stream.call_args.kwargs["max_tokens"] == 64_000


def test_anthropic_older_models_keep_their_small_limit():
    prov = _anthropic("claude-3-haiku-20240307")
    prov.generate([Message(role="user", content="hi")])
    assert prov.client.messages.create.call_args.kwargs["max_tokens"] == 4_096


def test_an_explicit_max_tokens_wins():
    prov = AnthropicProvider(model="claude-sonnet-4-20250514", api_key="x", max_tokens=1234)
    prov.client = MagicMock()
    prov.client.messages.create.return_value = MagicMock(content=[], usage=None)
    prov.generate([Message(role="user", content="hi")])
    assert prov.client.messages.create.call_args.kwargs["max_tokens"] == 1234
