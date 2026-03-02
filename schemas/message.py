from dataclasses import dataclass
from typing import Any


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str | None = None


@dataclass
class Message:
    role: str  # "system" | "user" | "tool" | "assistant"
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class Tool:
    name: str
    description: str
    arguments: dict[str, Any] = None


@dataclass
class LLMResponse:
    message: Message
    tool_calls: list[ToolCall] | None = None
    raw: Any | None = None
