"""
GitHub Copilot provider using the GitHub Copilot API.

Requires GitHub Copilot subscription and authentication.
Uses OpenAI-compatible API with GitHub's models.
"""

import json
import os

from openai import OpenAI

from providers.base import LLMProvider, ModelInfo
from schemas.message import LLMResponse, Message, ToolCall


class GitHubCopilotProvider(LLMProvider):
    name = "github_copilot"

    DEFAULT_MODELS = [
        "gpt-4o",
        "gpt-4o-mini",
        "claude-3.5-sonnet",
        "o1-preview",
        "o1-mini",
    ]

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        """
        Initialize GitHub Copilot provider.

        Args:
            model: Model to use (gpt-4o, claude-3.5-sonnet, etc.)
            api_key: GitHub token (defaults to GITHUB_TOKEN env var)
            base_url: Base URL for the API (defaults to GitHub Copilot API)
        """
        # GitHub Copilot uses GitHub tokens, not OpenAI keys
        token = api_key or os.getenv("GITHUB_TOKEN")
        if not token:
            raise ValueError(
                "GitHub token required. Set GITHUB_TOKEN env var or pass api_key parameter."
            )

        # GitHub Copilot API endpoint
        base = base_url or "https://api.githubcopilot.com"

        self.client = OpenAI(
            api_key=token,
            base_url=base,
        )
        self.model = model

    def list_models(self) -> list[ModelInfo]:
        """Fetch available models from GitHub Copilot API."""
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
            # GitHub Copilot API might not support model listing
            # Fall back to known available models
            return self._get_default_models()

    def _get_default_models(self) -> list[ModelInfo]:
        """Get hardcoded default models as fallback."""
        return [
            ModelInfo(
                id="gpt-4o",
                name="GPT-4o",
                description="OpenAI's GPT-4o via GitHub Copilot",
            ),
            ModelInfo(
                id="gpt-4o-mini",
                name="GPT-4o Mini",
                description="Faster, cheaper GPT-4o variant",
            ),
            ModelInfo(
                id="claude-3.5-sonnet",
                name="Claude 3.5 Sonnet",
                description="Anthropic's Claude 3.5 Sonnet via GitHub Copilot",
            ),
            ModelInfo(
                id="o1-preview",
                name="OpenAI o1 Preview",
                description="OpenAI's o1 reasoning model (preview)",
            ),
            ModelInfo(
                id="o1-mini",
                name="OpenAI o1 Mini",
                description="Smaller o1 reasoning model",
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
