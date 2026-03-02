from typing import List, Optional

from anthropic import Anthropic

from schemas.message import Message, LLMResponse, ToolCall
from providers.base import LLMProvider, ModelInfo


class AnthropicProvider(LLMProvider):
    """Anthropic/Claude provider with tool use support."""

    name = "anthropic"

    DEFAULT_MODELS = [
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307",
    ]

    def __init__(self, model: str = "claude-sonnet-4-20250514", api_key: Optional[str] = None):
        self.client = Anthropic(api_key=api_key)
        self.model = model

    def list_models(self) -> List[ModelInfo]:
        """Return available Claude models."""
        # Anthropic doesn't have a models list API, use defaults
        return [ModelInfo(id=m, name=m) for m in self.DEFAULT_MODELS]

    def generate(
        self,
        messages: List[Message],
        tools: Optional[list] = None,
        stream: bool = False,
    ) -> LLMResponse:
        # Extract system message (Anthropic handles it separately)
        system_content = None
        formatted_messages = []

        for msg in messages:
            if msg.role == "system":
                system_content = msg.content
            elif msg.role == "tool":
                # Anthropic expects tool results as user messages with tool_result blocks
                formatted_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id or msg.name,
                        "content": msg.content
                    }]
                })
            elif msg.role == "assistant":
                # Check if this was a tool-calling message (has metadata with tool_use_blocks)
                if msg.metadata and msg.metadata.get("tool_use_blocks"):
                    # Reconstruct assistant message with tool_use blocks
                    content = msg.metadata["tool_use_blocks"]
                else:
                    content = msg.content
                formatted_messages.append({"role": "assistant", "content": content})
            else:
                # User messages
                formatted_messages.append({"role": msg.role, "content": msg.content})

        # Format tools for Anthropic (uses input_schema instead of parameters)
        formatted_tools = None
        if tools:
            formatted_tools = []
            for tool in tools:
                formatted_tools.append({
                    "name": tool["name"],
                    "description": tool["description"],
                    "input_schema": tool.get("parameters", {"type": "object", "properties": {}})
                })

        # Build request kwargs
        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": formatted_messages,
        }
        if system_content:
            kwargs["system"] = system_content
        if formatted_tools:
            kwargs["tools"] = formatted_tools

        response = self.client.messages.create(**kwargs)

        # Parse response - Anthropic returns content as a list of blocks
        tool_calls = []
        text_content = ""
        tool_use_blocks = []  # Store for reconstructing assistant message later

        for block in response.content:
            if block.type == "text":
                text_content += block.text
            elif block.type == "tool_use":
                tool_call = ToolCall(
                    name=block.name,
                    arguments=block.input,  # Already a dict, not JSON string
                    id=block.id
                )
                tool_calls.append(tool_call)
                # Store the block for message reconstruction in history
                tool_use_blocks.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input
                })

        content = text_content if text_content else "Calling tool..."

        # Store tool_use_blocks in metadata for message reconstruction
        metadata = {"tool_use_blocks": tool_use_blocks} if tool_use_blocks else None

        return LLMResponse(
            message=Message(role="assistant", content=content, metadata=metadata),
            tool_calls=tool_calls if tool_calls else None,
            raw=response
        )
