"""Tests for cache markers on Anthropic models via OpenRouter."""

from unittest.mock import MagicMock

from providers.openrouter import OpenRouterProvider, add_cache_control
from schemas.message import Message

EPH = {"type": "ephemeral"}


def test_marks_first_system_and_last_user():
    msgs = [
        {"role": "system", "content": "BASE"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
    ]
    add_cache_control(msgs)
    assert msgs[0]["content"] == [{"type": "text", "text": "BASE", "cache_control": EPH}]
    assert msgs[3]["content"][-1]["cache_control"] == EPH
    assert msgs[1]["content"] == "q1" and msgs[2]["content"] == "a1"


def test_skips_tool_messages_and_empty_assistant_text():
    msgs = [
        {"role": "system", "content": "BASE"},
        {"role": "user", "content": "run it"},
        {"role": "assistant", "content": "I will check", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "out", "tool_call_id": "1"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "2"}]},
        {"role": "tool", "content": "out2", "tool_call_id": "2"},
    ]
    add_cache_control(msgs)
    assert msgs[2]["content"][-1]["cache_control"] == EPH  # last assistant with text
    assert msgs[3]["content"] == "out" and msgs[5]["content"] == "out2"
    assert msgs[4]["content"] == ""
    assert msgs[2]["tool_calls"] == [{"id": "1"}]


def test_image_message_marks_trailing_text_part():
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "u"}},
                {"type": "text", "text": "look"},
            ],
        }
    ]
    add_cache_control(msgs)
    assert msgs[0]["content"][-1]["cache_control"] == EPH
    assert "cache_control" not in msgs[0]["content"][0]


def test_no_messages_is_safe():
    add_cache_control([])


def _provider(model):
    prov = OpenRouterProvider(model=model, api_key="x")
    prov.client = MagicMock()
    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 1},
    }
    prov.client.post.return_value = resp
    return prov


def _sent(prov):
    return prov.client.post.call_args.kwargs["json"]["messages"]


def test_anthropic_models_get_markers():
    prov = _provider("anthropic/claude-sonnet-4")
    prov.generate([Message(role="system", content="S"), Message(role="user", content="hi")])
    assert str(_sent(prov)).count("cache_control") == 2


def test_other_models_unchanged():
    prov = _provider("openai/gpt-4o")
    prov.generate([Message(role="system", content="S"), Message(role="user", content="hi")])
    assert "cache_control" not in str(_sent(prov))
    assert _sent(prov)[1]["content"] == "hi"
