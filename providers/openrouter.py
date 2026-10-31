"""
OpenRouter Provider - Access multiple models through one API.
https://openrouter.ai/
"""

import json
from collections.abc import Callable

import httpx

from providers.base import (
    LLMProvider,
    ModelInfo,
    extract_token_usage,
    openai_user_content,
    post_chat,
)
from schemas.message import LLMResponse, Message, ToolCall


def _as_parts(content) -> list | None:
    """Content as OpenAI-style parts (so a cache marker can be attached), or None if empty."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else None
    return list(content) if content else None


def add_cache_control(formatted_messages: list[dict]) -> None:
    """Mark cache breakpoints for Anthropic models served through OpenRouter.

    OpenRouter forwards ``cache_control`` on content parts to Anthropic. Two breakpoints, like the
    native Anthropic provider: the first system message (stable prompt) and the last user/assistant
    message with real text (the conversation so far). Tool messages and empty text are skipped so
    the request stays valid. Mutates ``formatted_messages`` in place.
    """

    def mark(msg: dict) -> bool:
        parts = _as_parts(msg.get("content"))
        if not parts or not isinstance(parts[-1], dict) or parts[-1].get("type") != "text":
            return False
        parts[-1] = {**parts[-1], "cache_control": {"type": "ephemeral"}}
        msg["content"] = parts
        return True

    for msg in formatted_messages:
        if msg["role"] == "system":
            mark(msg)
            break
    for msg in reversed(formatted_messages):
        if msg["role"] in ("user", "assistant") and mark(msg):
            break


class OpenRouterProvider(LLMProvider):
    """
    OpenRouter provides access to many models through a single API.
    Supports: Claude, GPT-4, Llama, Mistral, and many more.
    """

    name = "openrouter"
    supports_images = True
    supports_streaming = True

    DEFAULT_MODELS = [
        "anthropic/claude-sonnet-4",
        "anthropic/claude-3.5-sonnet",
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
        "meta-llama/llama-3.3-70b-instruct",
        "google/gemini-2.0-flash-001",
        "mistralai/mistral-large-2411",
        "deepseek/deepseek-chat-v3-0324",
    ]

    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(
        self,
        model: str = "anthropic/claude-3.5-sonnet",
        api_key: str | None = None,
        site_url: str = "https://github.com/Amanbig/DevOrch",
        site_name: str = "DevOrch",
    ):
        self.model = model
        self.api_key = api_key
        self.site_url = site_url
        self.site_name = site_name
        self.client = httpx.Client(timeout=120.0)

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": self.site_url,
            "X-Title": self.site_name,
            "Content-Type": "application/json",
        }

    def list_models(self) -> list[ModelInfo]:
        """Fetch available models from OpenRouter API."""
        try:
            response = self.client.get(f"{self.BASE_URL}/models", headers=self._get_headers())
            response.raise_for_status()
            data = response.json()

            models = []
            for model in data.get("data", []):
                model_id = model.get("id", "")
                # Skip models that don't support chat or are deprecated
                architecture = model.get("architecture", {})
                if architecture.get("modality") == "text->image":
                    continue  # Skip image generation models

                models.append(
                    ModelInfo(
                        id=model_id,
                        name=model.get("name", model_id),
                        context_length=model.get("context_length"),
                        description=model.get("description"),
                    )
                )

            # Sort by name, prioritizing well-known providers
            def sort_key(m):
                priority_prefixes = [
                    "openai/",
                    "anthropic/",
                    "google/",
                    "meta-llama/",
                    "mistralai/",
                    "deepseek/",
                ]
                for i, prefix in enumerate(priority_prefixes):
                    if m.id.startswith(prefix):
                        return (i, m.name)
                return (len(priority_prefixes), m.name)

            models.sort(key=sort_key)
            return models if models else [ModelInfo(id=m, name=m) for m in self.DEFAULT_MODELS]

        except Exception:
            return [ModelInfo(id=m, name=m) for m in self.DEFAULT_MODELS]

    def generate(
        self,
        messages: list[Message],
        tools: list | None = None,
        stream: bool = False,
        on_text: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        # Format messages for OpenRouter API
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
                formatted_msg = {"role": msg.role, "content": openai_user_content(msg)}
            formatted_messages.append(formatted_msg)

        # Format tools (OpenAI-compatible format)
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

        if self.model.startswith("anthropic/"):
            add_cache_control(formatted_messages)

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": 0.0,
        }

        if formatted_tools:
            payload["tools"] = formatted_tools

        response = post_chat(
            self.client, f"{self.BASE_URL}/chat/completions", self._get_headers(), payload, on_text
        )

        # Handle errors with better messages
        if response.status_code == 404:
            raise Exception(
                f"Model '{self.model}' not found on OpenRouter. Try /model to select a different model."
            )
        elif response.status_code == 401:
            raise Exception("Invalid OpenRouter API key. Please check your API key.")
        elif response.status_code == 402:
            raise Exception("OpenRouter credits exhausted. Please add credits to your account.")

        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        message = choice["message"]

        tool_calls = []
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                args = (
                    json.loads(tc["function"]["arguments"])
                    if tc["function"].get("arguments")
                    else {}
                )
                tool_call = ToolCall(
                    name=tc["function"]["name"],
                    arguments=args,
                    id=tc.get("id", tc["function"]["name"]),
                )
                tool_calls.append(tool_call)

        content = message.get("content") or "Calling tool..."

        return LLMResponse(
            message=Message(role="assistant", content=content),
            tool_calls=tool_calls if tool_calls else None,
            raw=data,
            usage=extract_token_usage(data),
        )
