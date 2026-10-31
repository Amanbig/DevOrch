from anthropic import Anthropic

from providers.base import LLMProvider, ModelInfo
from schemas.message import LLMResponse, Message, TokenUsage, ToolCall


class AnthropicProvider(LLMProvider):
    """Anthropic/Claude provider with tool use support."""

    name = "anthropic"
    supports_images = True

    DEFAULT_MODELS = [
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307",
    ]

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,
        prompt_caching: bool = True,
    ):
        self.client = Anthropic(api_key=api_key)
        self.model = model
        # Cache tools + system prompt + conversation prefix. Prompts under the model's minimum
        # (1024-2048 tokens) are simply not cached, so this is safe to leave on.
        self.prompt_caching = prompt_caching

    def _system_blocks(self, texts: list[str]) -> list[dict] | str:
        """System prompt as blocks. The first (stable) block is the cache breakpoint.

        Anthropic's cache prefix order is tools -> system -> messages, so a breakpoint on the
        first system block caches the tool definitions and base prompt together. Later system
        texts (plan prompt, loop advisories) change between calls, so they stay after the
        breakpoint and don't invalidate it.
        """
        blocks = [{"type": "text", "text": t} for t in texts]
        if self.prompt_caching:
            blocks[0]["cache_control"] = {"type": "ephemeral"}
        return blocks

    @staticmethod
    def _mark_last_message(formatted_messages: list[dict]) -> None:
        """Put a cache breakpoint on the last content block so the whole conversation so far
        is cached; the next call in a tool loop then re-reads it at ~10% of the price."""
        if not formatted_messages:
            return
        last = formatted_messages[-1]
        content = last["content"]
        if isinstance(content, str):
            if not content:
                return
            content = [{"type": "text", "text": content}]
            last["content"] = content
        if content and isinstance(content[-1], dict):
            content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}

    def list_models(self) -> list[ModelInfo]:
        """Return available Claude models."""
        # Anthropic doesn't have a models list API, use defaults
        return [ModelInfo(id=m, name=m) for m in self.DEFAULT_MODELS]

    def generate(
        self,
        messages: list[Message],
        tools: list | None = None,
        stream: bool = False,
    ) -> LLMResponse:
        # Anthropic takes system text separately. Keep *all* system messages (the base prompt
        # plus plan-mode / loop-advisory additions) in order instead of letting the last win.
        system_texts: list[str] = []
        formatted_messages = []

        for msg in messages:
            if msg.role == "system":
                if msg.content:
                    system_texts.append(msg.content)
            elif msg.role == "tool":
                # Anthropic expects tool results as user messages with tool_result blocks
                formatted_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.tool_call_id or msg.name,
                                "content": msg.content,
                            }
                        ],
                    }
                )
            elif msg.role == "assistant":
                # Check if this was a tool-calling message (has metadata with tool_use_blocks)
                if msg.metadata and msg.metadata.get("tool_use_blocks"):
                    # Reconstruct assistant message with tool_use blocks
                    content = msg.metadata["tool_use_blocks"]
                else:
                    content = msg.content
                formatted_messages.append({"role": "assistant", "content": content})
            else:
                # User messages (with optional images)
                if msg.images:
                    blocks = [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": img.media_type,
                                "data": img.data,
                            },
                        }
                        for img in msg.images
                    ]
                    blocks.append({"type": "text", "text": msg.content})
                    formatted_messages.append({"role": msg.role, "content": blocks})
                else:
                    formatted_messages.append({"role": msg.role, "content": msg.content})

        # Format tools for Anthropic (uses input_schema instead of parameters)
        formatted_tools = None
        if tools:
            formatted_tools = []
            for tool in tools:
                formatted_tools.append(
                    {
                        "name": tool["name"],
                        "description": tool["description"],
                        "input_schema": tool.get(
                            "parameters", {"type": "object", "properties": {}}
                        ),
                    }
                )

        # Build request kwargs
        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": formatted_messages,
        }
        if system_texts:
            kwargs["system"] = self._system_blocks(system_texts)
        if formatted_tools:
            kwargs["tools"] = formatted_tools
        if self.prompt_caching:
            self._mark_last_message(formatted_messages)

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
                    id=block.id,
                )
                tool_calls.append(tool_call)
                # Store the block for message reconstruction in history
                tool_use_blocks.append(
                    {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                )

        content = text_content if text_content else "Calling tool..."

        # Store tool_use_blocks in metadata for message reconstruction
        metadata = {"tool_use_blocks": tool_use_blocks} if tool_use_blocks else None

        usage = None
        if hasattr(response, "usage") and response.usage:
            output_tokens = getattr(response.usage, "output_tokens", 0) or 0
            cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
            cache_write = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            # Anthropic's input_tokens excludes cached tokens; count all prompt tokens so the
            # numbers mean the same as for OpenAI (cached_tokens is the subset read from cache).
            input_tokens = (
                (getattr(response.usage, "input_tokens", 0) or 0) + cache_read + cache_write
            )
            usage = TokenUsage(
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                cached_tokens=cache_read,
            )

        return LLMResponse(
            message=Message(role="assistant", content=content, metadata=metadata),
            tool_calls=tool_calls if tool_calls else None,
            raw=response,
            usage=usage,
        )
