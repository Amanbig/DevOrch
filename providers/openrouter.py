"""
OpenRouter Provider - Access multiple models through one API.
https://openrouter.ai/
"""

import json
from typing import List, Optional
import httpx

from schemas.message import Message, LLMResponse, ToolCall
from providers.base import LLMProvider, ModelInfo


class OpenRouterProvider(LLMProvider):
    """
    OpenRouter provides access to many models through a single API.
    Supports: Claude, GPT-4, Llama, Mistral, and many more.
    """
    name = "openrouter"

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
        api_key: Optional[str] = None,
        site_url: str = "https://github.com/devpilot",
        site_name: str = "DevPilot"
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

    def list_models(self) -> List[ModelInfo]:
        """Fetch available models from OpenRouter API."""
        try:
            response = self.client.get(
                f"{self.BASE_URL}/models",
                headers=self._get_headers()
            )
            response.raise_for_status()
            data = response.json()

            models = []
            for model in data.get("data", []):
                model_id = model.get("id", "")
                # Skip models that don't support chat or are deprecated
                architecture = model.get("architecture", {})
                if architecture.get("modality") == "text->image":
                    continue  # Skip image generation models

                models.append(ModelInfo(
                    id=model_id,
                    name=model.get("name", model_id),
                    context_length=model.get("context_length"),
                    description=model.get("description"),
                ))

            # Sort by name, prioritizing well-known providers
            def sort_key(m):
                priority_prefixes = ["openai/", "anthropic/", "google/", "meta-llama/", "mistralai/", "deepseek/"]
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
        messages: List[Message],
        tools: Optional[list] = None,
        stream: bool = False,
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
                    "tool_calls": msg.metadata["tool_calls"]
                }
            else:
                formatted_msg = {"role": msg.role, "content": msg.content}
            formatted_messages.append(formatted_msg)

        # Format tools (OpenAI-compatible format)
        formatted_tools = None
        if tools:
            formatted_tools = []
            for tool in tools:
                formatted_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool.get("parameters", {"type": "object", "properties": {}})
                    }
                })

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": 0.0,
        }

        if formatted_tools:
            payload["tools"] = formatted_tools

        response = self.client.post(
            f"{self.BASE_URL}/chat/completions",
            headers=self._get_headers(),
            json=payload
        )

        # Handle errors with better messages
        if response.status_code == 404:
            raise Exception(f"Model '{self.model}' not found on OpenRouter. Try /model to select a different model.")
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
                args = json.loads(tc["function"]["arguments"]) if tc["function"].get("arguments") else {}
                tool_call = ToolCall(
                    name=tc["function"]["name"],
                    arguments=args,
                    id=tc.get("id", tc["function"]["name"])
                )
                tool_calls.append(tool_call)

        content = message.get("content") or "Calling tool..."

        return LLMResponse(
            message=Message(role="assistant", content=content),
            tool_calls=tool_calls if tool_calls else None,
            raw=data
        )
