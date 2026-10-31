import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from schemas.message import LLMResponse, Message, TokenUsage


class _ChatAccumulator:
    """Assembles streamed chat-completion deltas (text + fragmented tool calls) into one message."""

    def __init__(self, on_text: Callable[[str], None]):
        self.on_text = on_text
        self.parts: list[str] = []
        self.calls: dict[int, dict[str, str]] = {}
        self.usage: Any = None
        self.finish_reason: str | None = None

    def text(self, text: str | None) -> None:
        if text:
            self.parts.append(text)
            self.on_text(text)

    def tool_call(self, index: int | None, id: str | None, name: str | None, args: str | None):
        slot = self.calls.setdefault(index or 0, {"id": "", "name": "", "arguments": ""})
        if id:
            slot["id"] = id
        if name:
            slot["name"] += name
        if args:
            slot["arguments"] += args

    @property
    def content(self) -> str | None:
        return "".join(self.parts) or None

    def ordered_calls(self) -> list[dict[str, str]]:
        return [c for _, c in sorted(self.calls.items())]


def stream_chat_completion(client: Any, on_text: Callable[[str], None], **kwargs: Any) -> Any:
    """Run an OpenAI-style chat completion with streaming and return a non-streaming-shaped
    response (``.choices[0].message.content/.tool_calls`` and ``.usage``), so each provider's
    existing parsing code keeps working unchanged. ``on_text`` receives each text delta."""
    try:
        stream = client.chat.completions.create(
            stream=True, stream_options={"include_usage": True}, **kwargs
        )
    except Exception:
        # Some OpenAI-compatible servers reject stream_options; retry plainly (a real error,
        # e.g. bad credentials, will simply be raised again).
        stream = client.chat.completions.create(stream=True, **kwargs)

    acc = _ChatAccumulator(on_text)
    for chunk in stream:
        if getattr(chunk, "usage", None):
            acc.usage = chunk.usage
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        acc.finish_reason = getattr(choice, "finish_reason", None) or acc.finish_reason
        delta = choice.delta
        acc.text(getattr(delta, "content", None))
        for tc in getattr(delta, "tool_calls", None) or []:
            fn = getattr(tc, "function", None)
            acc.tool_call(
                tc.index,
                tc.id,
                getattr(fn, "name", None),
                getattr(fn, "arguments", None),
            )

    tool_calls = [
        SimpleNamespace(
            id=c["id"] or None,
            type="function",
            function=SimpleNamespace(name=c["name"], arguments=c["arguments"]),
        )
        for c in acc.ordered_calls()
    ]
    message = SimpleNamespace(content=acc.content, tool_calls=tool_calls or None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=acc.finish_reason)],
        usage=acc.usage,
    )


class _StreamedResponse:
    """Minimal httpx.Response look-alike for an already-consumed successful stream."""

    status_code = 200

    def __init__(self, data: dict[str, Any]):
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._data


def post_chat(
    client: Any,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    on_text: Callable[[str], None] | None = None,
) -> Any:
    """POST a chat completion over httpx, streaming (SSE) when ``on_text`` is given.

    Returns an object with ``status_code``, ``raise_for_status()`` and ``json()`` just like an
    httpx response, so callers' existing error handling and parsing are unchanged. If the server
    rejects the streaming request, this falls back to a normal request so errors surface through
    the usual path.
    """
    if on_text is None:
        return client.post(url, headers=headers, json=payload)

    for with_usage in (True, False):
        body = {**payload, "stream": True}
        if with_usage:
            body["stream_options"] = {"include_usage": True}
        with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code == 200:
                return _StreamedResponse(_read_sse(resp, on_text))
            resp.read()
            if resp.status_code not in (400, 422):
                break  # not a stream_options problem; let the plain request report it
    return client.post(url, headers=headers, json=payload)


def _read_sse(resp: Any, on_text: Callable[[str], None]) -> dict[str, Any]:
    """Consume an OpenAI-style SSE stream into a non-streaming-shaped JSON dict."""
    acc = _ChatAccumulator(on_text)
    for line in resp.iter_lines():
        if not line or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except ValueError:
            continue
        if chunk.get("usage"):
            acc.usage = chunk["usage"]
        choices = chunk.get("choices") or []
        if not choices:
            continue
        acc.finish_reason = choices[0].get("finish_reason") or acc.finish_reason
        delta = choices[0].get("delta") or {}
        acc.text(delta.get("content"))
        for tc in delta.get("tool_calls") or []:
            fn = tc.get("function") or {}
            acc.tool_call(tc.get("index"), tc.get("id"), fn.get("name"), fn.get("arguments"))

    message: dict[str, Any] = {"role": "assistant", "content": acc.content}
    calls = acc.ordered_calls()
    if calls:
        message["tool_calls"] = [
            {
                "id": c["id"] or None,
                "type": "function",
                "function": {"name": c["name"], "arguments": c["arguments"]},
            }
            for c in calls
        ]
    result: dict[str, Any] = {"choices": [{"message": message, "finish_reason": acc.finish_reason}]}
    if acc.usage:
        result["usage"] = acc.usage
    return result


def chat_create(client: Any, on_text: Callable[[str], None] | None = None, **kwargs: Any) -> Any:
    """``client.chat.completions.create`` that streams when ``on_text`` is given."""
    if on_text is None:
        return client.chat.completions.create(**kwargs)
    return stream_chat_completion(client, on_text, **kwargs)


def openai_user_content(msg: Message):
    """Message content in OpenAI chat format: a plain string, or text + image_url parts."""
    if not msg.images:
        return msg.content
    parts: list[dict[str, Any]] = [{"type": "text", "text": msg.content}]
    for img in msg.images:
        parts.append({"type": "image_url", "image_url": {"url": img.data_url}})
    return parts


def extract_token_usage(raw: Any) -> TokenUsage | None:
    """Extract standard TokenUsage from various provider response formats."""
    if not raw:
        return None
    try:
        # OpenAI, Groq, Mistral, OpenRouter, Together, DeepSeek, etc.
        if hasattr(raw, "usage") and raw.usage:
            prompt = getattr(raw.usage, "prompt_tokens", None)
            completion = getattr(raw.usage, "completion_tokens", None)
            if prompt is not None or completion is not None:
                prompt = prompt or 0
                completion = completion or 0
                total = getattr(raw.usage, "total_tokens", 0) or (prompt + completion)
                cached = 0
                prompt_details = getattr(raw.usage, "prompt_tokens_details", None)
                if prompt_details:
                    cached = getattr(prompt_details, "cached_tokens", 0) or 0
                return TokenUsage(
                    prompt_tokens=prompt,
                    completion_tokens=completion,
                    total_tokens=total,
                    cached_tokens=cached,
                )

            # Anthropic input_tokens / output_tokens
            input_tokens = getattr(raw.usage, "input_tokens", None)
            output_tokens = getattr(raw.usage, "output_tokens", None)
            if input_tokens is not None or output_tokens is not None:
                input_tokens = input_tokens or 0
                output_tokens = output_tokens or 0
                cached = getattr(raw.usage, "cache_read_input_tokens", 0) or 0
                written = getattr(raw.usage, "cache_creation_input_tokens", 0) or 0
                input_tokens += cached + written  # Anthropic's input_tokens excludes cache
                return TokenUsage(
                    prompt_tokens=input_tokens,
                    completion_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    cached_tokens=cached,
                )

        # Gemini SDK usage_metadata
        if hasattr(raw, "usage_metadata") and raw.usage_metadata:
            prompt = getattr(raw.usage_metadata, "prompt_token_count", 0) or 0
            completion = getattr(raw.usage_metadata, "candidates_token_count", 0) or 0
            total = getattr(raw.usage_metadata, "total_token_count", 0) or (prompt + completion)
            cached = getattr(raw.usage_metadata, "cached_content_token_count", 0) or 0
            return TokenUsage(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
                cached_tokens=cached,
            )

        # Dict format
        if isinstance(raw, dict):
            usage = raw.get("usage") or raw.get("usage_metadata")
            if isinstance(usage, dict):
                prompt = (
                    usage.get("prompt_tokens")
                    or usage.get("input_tokens")
                    or usage.get("prompt_token_count")
                    or 0
                )
                completion = (
                    usage.get("completion_tokens")
                    or usage.get("output_tokens")
                    or usage.get("candidates_token_count")
                    or 0
                )
                total = (
                    usage.get("total_tokens")
                    or usage.get("total_token_count")
                    or (prompt + completion)
                )
                cached = (
                    usage.get("cached_tokens")
                    or usage.get("cache_read_input_tokens")
                    or usage.get("cached_content_token_count")
                    or 0
                )
                return TokenUsage(
                    prompt_tokens=int(prompt),
                    completion_tokens=int(completion),
                    total_tokens=int(total),
                    cached_tokens=int(cached),
                )
    except Exception:
        pass
    return None


@dataclass
class ModelInfo:
    """Information about an available model."""

    id: str
    name: str
    context_length: int | None = None
    description: str | None = None


class LLMProvider(ABC):
    """
    Base interface for all LLM providers.
    """

    name: str
    model: str

    # True if this provider can send images to the model. Whether a *particular* model
    # accepts them still depends on the model; unsupported ones return an API error.
    supports_images: bool = False

    # True if generate() accepts ``on_text`` and streams text deltas to it as they arrive.
    supports_streaming: bool = False

    # Default models for this provider (can be overridden)
    DEFAULT_MODELS: list[str] = []

    @abstractmethod
    def generate(
        self,
        messages: list[Message],
        tools: list | None = None,
        stream: bool = False,
    ) -> LLMResponse:
        """
        Generate a response from the model.

        Providers with ``supports_streaming = True`` also accept ``on_text`` (a callback
        receiving each text delta) and still return the complete LLMResponse at the end.
        """
        pass

    def list_models(self) -> list[ModelInfo]:
        """
        List available models for this provider.
        Override in subclasses to fetch from API.
        Returns default models if not overridden.
        """
        return [ModelInfo(id=m, name=m) for m in self.DEFAULT_MODELS]

    @classmethod
    def get_default_models(cls) -> list[str]:
        """Get list of default model IDs."""
        return cls.DEFAULT_MODELS
