from dataclass import dataclass
from typing import List, Optional, Dict, Any


@dataclass
class Message:
    role: "system" | "user" | "tool" | "assistant"
    content: str
    name: Optional[str] = None
    metadata: Optional[Dict[str,Any]] = None


@dataclass
class Tool:
    name: str
    description: str
    arguments: [Dict[str,Any]] = None

@dataclass
class LLMResponse:
    message: Message
    tool_calls: Optional[List[ToolCall]] = None
    raw: Optional[Any] = None