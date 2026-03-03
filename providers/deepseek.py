"""
DeepSeek AI provider.

DeepSeek provides powerful reasoning and coding models with OpenAI-compatible API.
"""

import json

from openai import OpenAI

from providers.base import LLMProvider, ModelInfo
from schemas.message import LLMResponse, Message, ToolCall


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    DEFAULT_MODELS = [
        "deepseek-chat",
        "deepseek-coder",
        "deepseek-reasoner",
    ]

    def __init__(
        self,
        model: str = "deepseek-chat",
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com",
    ):
        """
        Initialize DeepSeek provider.

        Args:
            model: Model to use (deepseek-chat, deepseek-coder, deepseek-reasoner)
            api_key: DeepSeek API key (defaults to DEEPSEEK_API_KEY env var)
            base_url: Base URL for the API
        """
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def list_models(self) -> list[ModelInfo]:
        """Fetch available models from DeepSeek API."""
        try:
            response = self.client.models.list()
            models = []
            for model in response.data:
                models.append(
                    ModelInfo(
                        id=model.id,
                        name=model.id,
                        description=getattr(model, "description", None),
                    )
                )
            return models if models else self._get_default_models()
        except Exception:
            # Fallback to default models if API call fails
            return self._get_default_models()

    def _get_default_models(self) -> list[ModelInfo]:
        """Get hardcoded default models as fallback."""
        return [
            ModelInfo(
                id="deepseek-chat",
                name="DeepSeek Chat",
                context_length=64000,
                description="General-purpose conversational model",
            ),
            ModelInfo(
                id="deepseek-coder",
                name="DeepSeek Coder",
                context_length=64000,
                description="Specialized coding model",
            ),
            ModelInfo(
                id="deepseek-reasoner",
                name="DeepSeek Reasoner",
                context_length=64000,
                description="Advanced reasoning model (R1 series)",
            ),
        ]

    def generate(
        self,
        messages: list[Message],
        tools: list | None = None,
        stream: bool = False,
    ) -> LLMResponse:
        # Format messages for OpenAI-compatible API
        formatted_messages = []
        for msg in messages:
            if msg.role == "tool":
                formatted_msg = {
                    "role": "tool",
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id or msg.name,
                }
            elif msg.role == "assistant" and msg.metadata and msg.metadata.get("tool_calls"):
                formatted_msg = {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": msg.metadata["tool_calls"],
                }
            else:
                formatted_msg = {"role": msg.role, "content": msg.content}
            formatted_messages.append(formatted_msg)

        # Format tools
        formatted_tools = None
        if tools:
            formatted_tools = []
            for tool in tools:
                formatted_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "description": tool["description"],
                            "parameters": tool.get(
                                "parameters", {"type": "object", "properties": {}}
                            ),
                        },
                    }
                )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=formatted_messages,
            tools=formatted_tools,
            temperature=0.0,
        )

        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=json.loads(tc.function.arguments),
                    )
                )

        return LLMResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            metadata={
                "model": response.model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": (
                        response.usage.completion_tokens if response.usage else 0
                    ),
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                },
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in (message.tool_calls or [])
                ],
            },
        )
