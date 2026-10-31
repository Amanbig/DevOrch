"""Tests for streaming responses."""

import io
import json
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from core.agent import Agent
from core.executor import ToolExecutor
from core.modes import AgentMode, ModeManager
from core.planner import Planner
from providers.base import chat_create, stream_chat_completion
from providers.openai import OpenAIProvider
from schemas.message import LLMResponse, Message
from utils import logger
from utils.streaming import StreamRenderer


def chunk(content=None, tool_calls=None, finish=None, usage=None, choices=True):
    if not choices:
        return NS(choices=[], usage=usage)
    delta = NS(content=content, tool_calls=tool_calls)
    return NS(choices=[NS(delta=delta, finish_reason=finish)], usage=usage)


def tc(index, id=None, name=None, args=None):
    return NS(index=index, id=id, function=NS(name=name, arguments=args))


def fake_client(chunks, reject_stream_options=False):
    client = MagicMock()
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if reject_stream_options and "stream_options" in kwargs:
            raise TypeError("unexpected stream_options")
        return iter(chunks)

    client.chat.completions.create.side_effect = create
    client.calls = calls
    return client


def test_stream_accumulates_text_and_usage():
    usage = NS(prompt_tokens=7, completion_tokens=3, total_tokens=10)
    client = fake_client(
        [chunk("Hel"), chunk("lo"), chunk(None, finish="stop"), chunk(choices=False, usage=usage)]
    )
    seen = []
    resp = stream_chat_completion(client, seen.append, model="m", messages=[])
    assert seen == ["Hel", "lo"]
    assert resp.choices[0].message.content == "Hello"
    assert resp.choices[0].message.tool_calls is None
    assert resp.usage is usage
    assert client.calls[0]["stream"] is True
    assert client.calls[0]["stream_options"] == {"include_usage": True}


def test_stream_assembles_tool_calls_across_chunks():
    client = fake_client(
        [
            chunk(tool_calls=[tc(0, id="call_1", name="shell", args='{"comm')]),
            chunk(tool_calls=[tc(0, args='and": "ls"}')]),
            chunk(tool_calls=[tc(1, id="call_2", name="grep", args="{}")]),
        ]
    )
    resp = stream_chat_completion(client, lambda t: None, model="m", messages=[])
    calls = resp.choices[0].message.tool_calls
    assert [c.id for c in calls] == ["call_1", "call_2"]
    assert calls[0].function.name == "shell"
    assert json.loads(calls[0].function.arguments) == {"command": "ls"}
    assert resp.choices[0].message.content is None


def test_stream_options_fallback():
    client = fake_client([chunk("ok")], reject_stream_options=True)
    resp = stream_chat_completion(client, lambda t: None, model="m", messages=[])
    assert resp.choices[0].message.content == "ok"
    assert "stream_options" not in client.calls[-1]


def test_chat_create_without_callback_is_plain_call():
    client = MagicMock()
    chat_create(client, None, model="m")
    client.chat.completions.create.assert_called_once_with(model="m")


def test_openai_provider_streams_and_parses_tool_calls():
    prov = OpenAIProvider(api_key="x")
    prov.client = fake_client(
        [
            chunk("Let me look. "),
            chunk(tool_calls=[tc(0, id="c1", name="shell", args='{"command":"ls"}')]),
        ]
    )
    seen = []
    resp = prov.generate([Message(role="user", content="hi")], on_text=seen.append)
    assert seen == ["Let me look. "]
    assert resp.message.content == "Let me look. "
    assert resp.tool_calls[0].name == "shell" and resp.tool_calls[0].arguments == {"command": "ls"}
    assert resp.tool_calls[0].id == "c1"


def test_anthropic_provider_streams():
    from providers.anthropic import AnthropicProvider

    prov = AnthropicProvider(api_key="x")
    final = MagicMock()
    final.content = [NS(type="text", text="Hello")]
    final.usage = None
    ctx = MagicMock()
    ctx.__enter__.return_value.text_stream = iter(["Hel", "lo"])
    ctx.__enter__.return_value.get_final_message.return_value = final
    prov.client = MagicMock()
    prov.client.messages.stream.return_value = ctx
    seen = []
    resp = prov.generate([Message(role="user", content="hi")], on_text=seen.append)
    assert seen == ["Hel", "lo"] and resp.message.content == "Hello"
    prov.client.messages.create.assert_not_called()


def test_streaming_flags():
    from providers import PROVIDERS

    for name, cls in PROVIDERS.items():
        assert cls.supports_streaming, name


# ── renderer + print_response dedupe ────────────────────────────────────────


def _console():
    return Console(file=io.StringIO(), force_terminal=False, width=80)


def test_renderer_collects_text_and_prints_it():
    con = _console()
    with StreamRenderer(con) as r:
        r.write("Hello ")
        r.write("**world**")
    r.finish(is_final_answer=False)
    assert r.text == "Hello **world**"
    assert "Hello" in con.file.getvalue()


def test_renderer_no_text_is_harmless():
    con = _console()
    with StreamRenderer(con) as r:
        pass
    r.finish(is_final_answer=True)
    assert r.text == ""


def test_print_response_skips_text_already_streamed(monkeypatch):
    con = _console()
    monkeypatch.setattr(logger, "console", con)
    logger.mark_streamed("  final answer \n")
    logger.print_response("final answer")
    assert con.file.getvalue() == ""
    # only skips once
    logger.print_response("final answer")
    assert "final answer" in con.file.getvalue()


def test_print_response_prints_when_text_differs(monkeypatch):
    con = _console()
    monkeypatch.setattr(logger, "console", con)
    logger.mark_streamed("something else")
    logger.print_response("different")
    assert "different" in con.file.getvalue()


# ── agent integration ───────────────────────────────────────────────────────


class _Prov:
    name = "p"
    model = "m"
    supports_images = False

    def __init__(self, streaming):
        self.supports_streaming = streaming
        self.got_on_text = None

    def generate(self, messages, tools=None, stream=False, on_text=None):
        self.got_on_text = on_text
        if on_text:
            on_text("streamed ")
            on_text("answer")
        return LLMResponse(message=Message(role="assistant", content="streamed answer"))


class _PlainProv(_Prov):
    def generate(self, messages, tools=None, stream=False):  # no on_text parameter at all
        return LLMResponse(message=Message(role="assistant", content="plain answer"))


def _agent(prov, stream_output):
    class P(Planner):
        def plan(self, history):
            return history

    a = Agent(
        provider=prov,
        planner=P(),
        executor=ToolExecutor([], require_confirmation=False),
        tools=[],
        mode_manager=ModeManager(default_mode=AgentMode.AUTO),
    )
    a.stream_output = stream_output
    return a


def test_agent_streams_when_enabled_and_supported(monkeypatch):
    con = _console()
    monkeypatch.setattr("core.agent.console", con)
    monkeypatch.setattr(logger, "console", con)
    prov = _Prov(streaming=True)
    result = _agent(prov, True).run("hi")
    assert result == "streamed answer" and prov.got_on_text is not None
    out_before = con.file.getvalue()
    logger.print_response(result)  # should not duplicate what was streamed live
    assert con.file.getvalue() == out_before


def test_agent_does_not_stream_when_disabled():
    prov = _Prov(streaming=True)
    _agent(prov, False).run("hi")
    assert prov.got_on_text is None


def test_agent_falls_back_for_non_streaming_provider():
    prov = _PlainProv(streaming=False)
    assert _agent(prov, True).run("hi") == "plain answer"


def test_agent_tool_call_text_is_not_marked_as_final(monkeypatch):
    con = _console()
    monkeypatch.setattr("core.agent.console", con)
    monkeypatch.setattr(logger, "console", con)
    monkeypatch.setattr(logger, "_streamed_text", None)
    r = StreamRenderer(con)
    with r:
        r.write("thinking")
    r.finish(is_final_answer=False)
    assert logger._streamed_text is None


@pytest.fixture(autouse=True)
def _reset_streamed():
    logger._streamed_text = None
    yield
    logger._streamed_text = None


# ── httpx / SSE providers ───────────────────────────────────────────────────

from providers.base import post_chat  # noqa: E402
from providers.groq import GroqProvider  # noqa: E402


def sse(*events):
    lines = []
    for e in events:
        lines.append("data: " + (e if isinstance(e, str) else json.dumps(e)))
        lines.append("")
    return lines


def delta_event(content=None, tool_calls=None, finish=None, usage=None):
    ev = {
        "choices": [
            {"delta": {"content": content, "tool_calls": tool_calls}, "finish_reason": finish}
        ]
    }
    if usage:
        ev["usage"] = usage
    return ev


class FakeStream:
    def __init__(self, status, lines=()):
        self.status_code = status
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b""

    def iter_lines(self):
        return iter(self._lines)


def fake_http(streams, post_resp=None):
    client = MagicMock()
    client.stream.side_effect = list(streams)
    client.post.return_value = post_resp
    return client


def test_sse_text_tool_calls_and_usage():
    lines = sse(
        delta_event("Hi "),
        delta_event("there"),
        delta_event(
            tool_calls=[
                {"index": 0, "id": "c1", "function": {"name": "shell", "arguments": '{"command"'}}
            ]
        ),
        delta_event(
            tool_calls=[{"index": 0, "function": {"arguments": ': "ls"}'}}], finish="tool_calls"
        ),
        {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2}},
        "[DONE]",
    )
    client = fake_http([FakeStream(200, lines)])
    seen = []
    resp = post_chat(client, "http://x", {}, {"model": "m"}, seen.append)
    data = resp.json()
    assert seen == ["Hi ", "there"] and resp.status_code == 200
    msg = data["choices"][0]["message"]
    assert msg["content"] == "Hi there"
    assert msg["tool_calls"][0]["function"] == {"name": "shell", "arguments": '{"command": "ls"}'}
    assert msg["tool_calls"][0]["id"] == "c1"
    assert data["usage"] == {"prompt_tokens": 5, "completion_tokens": 2}
    body = client.stream.call_args.kwargs["json"]
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True}


def test_sse_ignores_comments_and_bad_json():
    lines = [": keepalive", "data: {not json", *sse(delta_event("ok"), "[DONE]")]
    resp = post_chat(fake_http([FakeStream(200, lines)]), "u", {}, {}, lambda t: None)
    assert resp.json()["choices"][0]["message"]["content"] == "ok"


def test_sse_retries_without_stream_options_on_400():
    client = fake_http([FakeStream(400), FakeStream(200, sse(delta_event("ok"), "[DONE]"))])
    resp = post_chat(client, "u", {}, {}, lambda t: None)
    assert resp.json()["choices"][0]["message"]["content"] == "ok"
    assert "stream_options" not in client.stream.call_args_list[1].kwargs["json"]


def test_sse_falls_back_to_plain_post_on_error():
    plain = MagicMock(status_code=401)
    client = fake_http([FakeStream(401)], post_resp=plain)
    assert post_chat(client, "u", {}, {"model": "m"}, lambda t: None) is plain
    client.post.assert_called_once_with("u", headers={}, json={"model": "m"})


def test_post_chat_without_callback_is_plain_post():
    client = MagicMock()
    post_chat(client, "u", {"h": "1"}, {"p": 1}, None)
    client.post.assert_called_once_with("u", headers={"h": "1"}, json={"p": 1})
    client.stream.assert_not_called()


def test_groq_provider_streams_end_to_end():
    prov = GroqProvider(api_key="x")
    prov.client = fake_http(
        [
            FakeStream(
                200,
                sse(
                    delta_event("Looking. "),
                    delta_event(
                        tool_calls=[
                            {
                                "index": 0,
                                "id": "c9",
                                "function": {"name": "grep", "arguments": "{}"},
                            }
                        ]
                    ),
                    "[DONE]",
                ),
            )
        ]
    )
    seen = []
    resp = prov.generate([Message(role="user", content="hi")], on_text=seen.append)
    assert seen == ["Looking. "] and resp.message.content == "Looking. "
    assert resp.tool_calls[0].name == "grep" and resp.tool_calls[0].id == "c9"


def test_gemini_provider_streams_text_and_function_calls():
    from providers.gemini import GeminiProvider

    def part(text=None, fc=None):
        return NS(text=text, function_call=fc)

    def gchunk(parts, usage=None):
        return NS(candidates=[NS(content=NS(parts=parts))], usage_metadata=usage)

    usage = NS(
        prompt_token_count=4,
        candidates_token_count=2,
        total_token_count=6,
        cached_content_token_count=0,
    )
    prov = GeminiProvider(api_key="x")
    prov.client = MagicMock()
    prov.client.models.generate_content_stream.return_value = iter(
        [
            gchunk([part("Hello ")]),
            gchunk([part("world"), part(fc=NS(name="shell", args={"command": "ls"}))], usage),
        ]
    )
    seen = []
    resp = prov.generate([Message(role="user", content="hi")], on_text=seen.append)
    assert seen == ["Hello ", "world"] and resp.message.content == "Hello world"
    assert resp.tool_calls[0].name == "shell" and resp.tool_calls[0].arguments == {"command": "ls"}
    assert resp.usage.total_tokens == 6
    prov.client.models.generate_content.assert_not_called()
