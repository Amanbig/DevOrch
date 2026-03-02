from dataclasses import dataclass
from typing import List, Optional, Dict, Any

@dataclass
class ToolCall:
    name: str
    arguments: Dict[str, Any]

@dataclass
class Message:
    role: str # "system" | "user" | "tool" | "assistant"
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    metadata: Optional[Dict[str,Any]] = None

@dataclass
class Tool:
    name: str
    description: str
    arguments: Dict[str, Any] = None

@dataclass
class LLMResponse:
    message: Message
    tool_calls: Optional[List[ToolCall]] = None
    raw: Optional[Any] = None