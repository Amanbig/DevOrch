"""
Custom provider for OpenAI-compatible APIs.

Allows users to connect to any OpenAI-compatible endpoint with custom configuration.
Perfect for self-hosted models, custom endpoints, or providers not officially supported.
"""

import json
import os

from openai import OpenAI

from providers.base import LLMProvider, ModelInfo
from schemas.message import LLMResponse, Message, ToolCall


class CustomProvider(LLMProvider):
    """
    Generic OpenAI-compatible provider.

    Can be configured to work with any API that implements the OpenAI chat completions format.

    Examples:
    - Self-hosted vLLM, TGI, or llama.cpp servers
    - Custom model endpoints
    - Provider-specific endpoints not officially supported
    """

    name = "custom"

    DEFAULT_MODELS = []  # User must specify model

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str | None = None,
        default_models: list[str] | None = None,
    ):
        """
        Initialize custom provider.

        Args:
            model: Model name/ID to use
            base_url: Base URL for the API endpoint (e.g., "http://localhost:8000/v1")
            api_key: API key (optional, some self-hosted models don't need it)
            default_models: List of available models (optional)
        """
        if not base_url:
            raise ValueError("base_url is required for custom provider")

        if not model:
            raise ValueError("model is required for custom provider")

        # Use provided API key or "dummy" for self-hosted models that don't need auth
        key = api_key or os.getenv("CUSTOM_API_KEY") or "dummy"

        self.client = OpenAI(
            api_key=key,
            base_url=base_url,
        )
        self.model = model
        self.base_url = base_url

        # Update default models if provided
        if default_models:
            self.DEFAULT_MODELS = default_models

    def list_models(self) -> list[ModelInfo]:
        """
        List available models.

        Tries to fetch from API, falls back to configured defaults.
        """
        try:
            response = self.client.models.list()
            models = []
            for model in response.data:
                models.append(
                    ModelInfo(
                        id=model.id,
                        name=model.id,
                    )
                )
            return models if models else [ModelInfo(id=self.model, name=self.model)]
        except Exception:
            # If API doesn't support model listing, return configured model
            if self.DEFAULT_MODELS:
                return [ModelInfo(id=m, name=m) for m in self.DEFAULT_MODELS]
            return [ModelInfo(id=self.model, name=self.model)]

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
                # Preserve tool_calls in assistant messages
                formatted_msg = {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": msg.metadata["tool_calls"],
                }
            else:
                formatted_msg = {"role": msg.role, "content": msg.content}
            formatted_messages.append(formatted_msg)

        # Format tools for OpenAI-compatible API
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

        # Make the API call
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=formatted_messages,
                tools=formatted_tools if formatted_tools else None,
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

        except Exception as e:
            raise RuntimeError(f"Error calling custom API at {self.base_url}: {e}") from e
