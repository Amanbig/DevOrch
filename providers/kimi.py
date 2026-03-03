"""
Kimi (Moonshot AI) provider.

Moonshot AI's Kimi model with extremely long context (200K+ tokens).
Uses OpenAI-compatible API.
"""

import json

from openai import OpenAI

from providers.base import LLMProvider, ModelInfo
from schemas.message import LLMResponse, Message, ToolCall


class KimiProvider(LLMProvider):
    name = "kimi"

    DEFAULT_MODELS = [
        "moonshot-v1-8k",
        "moonshot-v1-32k",
        "moonshot-v1-128k",
    ]

    def __init__(
        self,
        model: str = "moonshot-v1-32k",
        api_key: str | None = None,
        base_url: str = "https://api.moonshot.cn/v1",
    ):
        """
        Initialize Kimi provider.

        Args:
            model: Model to use (moonshot-v1-8k, moonshot-v1-32k, moonshot-v1-128k)
            api_key: Moonshot API key (defaults to MOONSHOT_API_KEY env var)
            base_url: Base URL for the API
        """
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def list_models(self) -> list[ModelInfo]:
        """Fetch available models from Moonshot AI API."""
        try:
            response = self.client.models.list()
            models = []
            for model in response.data:
                # Extract context length from model ID if possible
                context = None
                if "8k" in model.id.lower():
                    context = 8000
                elif "32k" in model.id.lower():
                    context = 32000
                elif "128k" in model.id.lower():
                    context = 128000

                models.append(
                    ModelInfo(
                        id=model.id,
                        name=model.id,
                        context_length=context,
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
                id="moonshot-v1-8k",
                name="Kimi 8K",
                context_length=8000,
                description="Fast model with 8K context",
            ),
            ModelInfo(
                id="moonshot-v1-32k",
                name="Kimi 32K",
                context_length=32000,
                description="Balanced model with 32K context",
            ),
            ModelInfo(
                id="moonshot-v1-128k",
                name="Kimi 128K",
                context_length=128000,
                description="Long context model with 128K tokens",
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
