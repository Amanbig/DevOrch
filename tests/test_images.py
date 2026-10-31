"""Tests for multimodal message formatting and gating."""

import base64
from unittest.mock import MagicMock

import pytest

from core.agent import Agent
from core.context import IMAGE_TOKEN_ESTIMATE, count_message_tokens
from core.images import downscale, load_image, prune_old_images
from providers import PROVIDERS
from providers.base import openai_user_content
from providers.openai import OpenAIProvider
from schemas.message import ImageData, LLMResponse, Message

IMG = ImageData(media_type="image/png", data=base64.b64encode(b"pngbytes").decode(), name="a.png")


def test_openai_content_plain_without_images():
    assert openai_user_content(Message(role="user", content="hi")) == "hi"


def test_openai_content_with_images():
    parts = openai_user_content(Message(role="user", content="hi", images=[IMG]))
    assert parts[0] == {"type": "text", "text": "hi"}
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_token_estimate_counts_images():
    plain = count_message_tokens(Message(role="user", content="hi"))
    withimg = count_message_tokens(Message(role="user", content="hi", images=[IMG, IMG]))
    assert withimg == plain + 2 * IMAGE_TOKEN_ESTIMATE


def test_openai_provider_sends_image_parts(monkeypatch):
    prov = OpenAIProvider(api_key="x")
    create = MagicMock()
    create.return_value.choices = [MagicMock(message=MagicMock(content="ok", tool_calls=None))]
    create.return_value.usage = None
    prov.client = MagicMock()
    prov.client.chat.completions.create = create
    prov.generate([Message(role="user", content="look", images=[IMG])])
    sent = create.call_args.kwargs["messages"][0]["content"]
    assert isinstance(sent, list) and sent[1]["image_url"]["url"] == IMG.data_url


def test_anthropic_provider_sends_image_blocks():
    from providers.anthropic import AnthropicProvider

    prov = AnthropicProvider(api_key="x")
    prov.client = MagicMock()
    resp = MagicMock()
    resp.content = []
    resp.usage = None
    prov.client.messages.create.return_value = resp
    prov.generate([Message(role="user", content="look", images=[IMG])])
    content = prov.client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/png"
    assert content[-1] == {"type": "text", "text": "look"}


def test_gemini_provider_sends_inline_image(monkeypatch):
    from providers.gemini import GeminiProvider

    prov = GeminiProvider(api_key="x")
    prov.client = MagicMock()
    prov.client.models.generate_content.return_value = MagicMock(
        candidates=[MagicMock(content=MagicMock(parts=[MagicMock(text="ok", function_call=None)]))],
        usage_metadata=None,
    )
    prov.generate([Message(role="user", content="look", images=[IMG])])
    contents = prov.client.models.generate_content.call_args.kwargs["contents"]
    assert len(contents[0].parts) == 2
    assert contents[0].parts[1].inline_data.mime_type == "image/png"


def test_vision_flags():
    assert PROVIDERS["openai"].supports_images
    assert PROVIDERS["anthropic"].supports_images
    assert PROVIDERS["gemini"].supports_images
    assert not PROVIDERS["deepseek"].supports_images


class _TextOnly:
    name = "textonly"
    model = "m"
    supports_images = False

    def __init__(self):
        self.seen = None

    def generate(self, messages, tools=None, stream=False):
        self.seen = messages
        return LLMResponse(message=Message(role="assistant", content="done"), tool_calls=None)


def _agent(provider):
    from core.executor import ToolExecutor
    from core.modes import AgentMode, ModeManager
    from core.planner import Planner

    mm = ModeManager(default_mode=AgentMode.AUTO)

    class P(Planner):
        def plan(self, history):
            return history

    return Agent(
        provider=provider,
        planner=P(),
        executor=ToolExecutor([], require_confirmation=False),
        tools=[],
        mode_manager=mm,
    )


def test_agent_drops_images_for_unsupported_provider():
    prov = _TextOnly()
    agent = _agent(prov)
    agent.run("hi", images=[IMG])
    assert all(not m.images for m in prov.seen)


def test_agent_keeps_images_for_supported_provider():
    prov = _TextOnly()
    prov.supports_images = True
    agent = _agent(prov)
    agent.run("hi", images=[IMG])
    assert any(m.images for m in prov.seen)


# ── token savings ───────────────────────────────────────────────────────────


def _msgs(n_images: int):
    out = []
    for i in range(n_images):
        out.append(
            Message(
                role="user", content=f"q{i}", images=[ImageData("image/png", "AA", f"s{i}.png")]
            )
        )
        out.append(Message(role="assistant", content=f"a{i}"))
    return out


def test_prune_keeps_only_recent_images():
    msgs = _msgs(4)
    pruned = prune_old_images(msgs, keep=2)
    with_images = [m for m in pruned if m.images]
    assert [m.content for m in with_images] == ["q2", "q3"]
    assert "s0.png" in pruned[0].content and "omitted" in pruned[0].content
    assert pruned[0].images is None


def test_prune_does_not_mutate_history():
    msgs = _msgs(3)
    prune_old_images(msgs, keep=1)
    assert all(m.images for m in msgs if m.role == "user")
    assert msgs[0].content == "q0"


def test_prune_noop_when_within_limit():
    msgs = _msgs(2)
    assert prune_old_images(msgs, keep=2) is msgs


def test_agent_sends_pruned_history():
    prov = _TextOnly()
    prov.supports_images = True
    agent = _agent(prov)
    agent.keep_recent_images = 1
    agent.run("first", images=[IMG])
    agent.run("second", images=[IMG])
    sent_with_images = [m for m in prov.seen if m.images]
    assert len(sent_with_images) == 1 and sent_with_images[0].content == "second"
    assert any("omitted" in m.content for m in prov.seen if m.content.startswith("first"))
    # stored history keeps the original
    assert sum(1 for m in agent.history if m.images) == 2


def test_downscale_shrinks_large_image(tmp_path):
    PIL = pytest.importorskip("PIL.Image")
    big = tmp_path / "big.png"
    PIL.new("RGB", (4000, 2000), (10, 120, 200)).save(big)
    image, warn = load_image(big)
    assert warn is None
    raw = base64.b64decode(image.data)
    with PIL.open(__import__("io").BytesIO(raw)) as out:
        assert max(out.size) == 1568 and out.size[0] / out.size[1] == pytest.approx(2, rel=0.01)
    assert len(raw) < big.stat().st_size


def test_downscale_leaves_small_and_gif_alone():
    PIL = pytest.importorskip("PIL.Image")
    import io

    buf = io.BytesIO()
    PIL.new("RGB", (100, 100)).save(buf, "PNG")
    data = buf.getvalue()
    assert downscale(data, "image/png") == (data, "image/png")
    assert downscale(b"GIF89a....", "image/gif") == (b"GIF89a....", "image/gif")


def test_downscale_survives_garbage():
    pytest.importorskip("PIL")
    junk = b"not an image at all"
    assert downscale(junk, "image/png") == (junk, "image/png")
