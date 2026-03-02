"""
Groq Provider - Fast AI inference
https://groq.com/
"""

import json

import httpx

from providers.base import LLMProvider, ModelInfo
from schemas.message import LLMResponse, Message, ToolCall


class GroqProvider(LLMProvider):
    """
    Groq provider for ultra-fast inference.
    Supports Llama, Mixtral, and Gemma models.
    """

    name = "groq"

    DEFAULT_MODELS = [
        "llama-3.1-70b-versatile",
        "llama-3.1-8b-instant",
        "llama3-70b-8192",
        "llama3-8b-8192",
        "mixtral-8x7b-32768",
        "gemma2-9b-it",
        "gemma-7b-it",
    ]

    BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(
        self,
        model: str = "llama-3.1-70b-versatile",
        api_key: str | None = None,
    ):
        self.model = model
        self.api_key = api_key
        self.client = httpx.Client(timeout=120.0)

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def list_models(self) -> list[ModelInfo]:
        """Fetch available models from Groq API."""
        try:
            response = self.client.get(f"{self.BASE_URL}/models", headers=self._get_headers())
            response.raise_for_status()
            data = response.json()

            models = []
            for model in data.get("data", []):
                # Filter to active models
                if model.get("active", True):
                    models.append(
                        ModelInfo(
                            id=model.get("id"),
                            name=model.get("id"),
                            context_length=model.get("context_window"),
                        )
                    )

            models.sort(key=lambda m: m.id)
            return models if models else [ModelInfo(id=m, name=m) for m in self.DEFAULT_MODELS]

        except Exception:
            return [ModelInfo(id=m, name=m) for m in self.DEFAULT_MODELS]

    def generate(
        self,
        messages: list[Message],
        tools: list | None = None,
        stream: bool = False,
    ) -> LLMResponse:
        # Format messages for Groq API
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

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": 0.0,
        }

        if formatted_tools:
            payload["tools"] = formatted_tools
            payload["tool_choice"] = "auto"

        response = self.client.post(
            f"{self.BASE_URL}/chat/completions", headers=self._get_headers(), json=payload
        )
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
        )
