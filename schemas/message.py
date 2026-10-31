from dataclasses import dataclass
from typing import Any


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str | None = None


@dataclass
class ImageData:
    """An image attached to a user message (base64-encoded, not persisted to sessions)."""

    media_type: str  # e.g. "image/png"
    data: str  # base64 without the data: prefix
    name: str = ""

    @property
    def data_url(self) -> str:
        return f"data:{self.media_type};base64,{self.data}"


@dataclass
class Message:
    role: str  # "system" | "user" | "tool" | "assistant"
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, Any] | None = None
    images: list[ImageData] | None = None


@dataclass
class Tool:
    name: str
    description: str
    arguments: dict[str, Any] = None


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0


@dataclass
class LLMResponse:
    message: Message
    tool_calls: list[ToolCall] | None = None
    raw: Any | None = None
    usage: TokenUsage | None = None
