"""Tests for Anthropic system-prompt handling and prompt caching."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from providers.anthropic import AnthropicProvider
from providers.base import extract_token_usage
from schemas.message import ImageData, Message


def _provider(caching=True):
    prov = AnthropicProvider(api_key="x", prompt_caching=caching)
    prov.client = MagicMock()
    resp = MagicMock()
    resp.content = []
    resp.usage = None
    prov.client.messages.create.return_value = resp
    return prov


def _kwargs(prov):
    return prov.client.messages.create.call_args.kwargs


TOOLS = [{"name": "t", "description": "d", "parameters": {"type": "object", "properties": {}}}]


def test_all_system_messages_kept_in_order():
    prov = _provider()
    prov.generate(
        [
            Message(role="system", content="BASE"),
            Message(role="system", content="PLAN"),
            Message(role="user", content="hi"),
            Message(role="system", content="ADVISORY"),
        ],
        tools=TOOLS,
    )
    blocks = _kwargs(prov)["system"]
    assert [b["text"] for b in blocks] == ["BASE", "PLAN", "ADVISORY"]


def test_cache_breakpoint_only_on_stable_first_system_block():
    prov = _provider()
    prov.generate(
        [
            Message(role="system", content="BASE"),
            Message(role="system", content="ADVISORY"),
            Message(role="user", content="hi"),
        ]
    )
    blocks = _kwargs(prov)["system"]
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in blocks[1]


def test_last_message_gets_breakpoint_string_content_converted():
    prov = _provider()
    prov.generate([Message(role="system", content="S"), Message(role="user", content="hello")])
    last = _kwargs(prov)["messages"][-1]["content"]
    assert last == [{"type": "text", "text": "hello", "cache_control": {"type": "ephemeral"}}]


def test_breakpoint_on_tool_result_block():
    prov = _provider()
    prov.generate(
        [
            Message(role="system", content="S"),
            Message(role="user", content="run"),
            Message(role="tool", content="output", tool_call_id="abc"),
        ]
    )
    msgs = _kwargs(prov)["messages"]
    assert msgs[-1]["content"][-1]["type"] == "tool_result"
    assert msgs[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in str(msgs[0])  # earlier messages untouched


def test_breakpoint_on_text_after_image():
    prov = _provider()
    img = ImageData("image/png", "AA", "a.png")
    prov.generate([Message(role="user", content="look", images=[img])])
    content = _kwargs(prov)["messages"][-1]["content"]
    assert content[0]["type"] == "image" and "cache_control" not in content[0]
    assert content[-1]["cache_control"] == {"type": "ephemeral"}


def test_at_most_two_breakpoints():
    prov = _provider()
    prov.generate(
        [Message(role="system", content="S"), Message(role="user", content="a")], tools=TOOLS
    )
    assert str(_kwargs(prov)).count("cache_control") == 2


def test_caching_disabled():
    prov = _provider(caching=False)
    prov.generate([Message(role="system", content="S"), Message(role="user", content="hello")])
    kw = _kwargs(prov)
    assert "cache_control" not in str(kw)
    assert kw["messages"][-1]["content"] == "hello"


def test_no_system_message():
    prov = _provider()
    prov.generate([Message(role="user", content="hi")])
    assert "system" not in _kwargs(prov)


def test_usage_counts_cache_tokens_in_prompt_total():
    prov = _provider()
    prov.client.messages.create.return_value.usage = SimpleNamespace(
        input_tokens=50,
        output_tokens=10,
        cache_read_input_tokens=900,
        cache_creation_input_tokens=100,
    )
    usage = prov.generate([Message(role="user", content="hi")]).usage
    assert usage.prompt_tokens == 1050
    assert usage.cached_tokens == 900
    assert usage.total_tokens == 1060


def test_extract_token_usage_anthropic_fallback_includes_cache():
    raw = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=5,
            output_tokens=2,
            cache_read_input_tokens=100,
            cache_creation_input_tokens=0,
        )
    )
    usage = extract_token_usage(raw)
    assert usage.prompt_tokens == 105 and usage.cached_tokens == 100
