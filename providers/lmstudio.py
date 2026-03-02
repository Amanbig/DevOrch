"""
LM Studio Provider - Local models via OpenAI-compatible API
https://lmstudio.ai/
"""

import json

import httpx

from providers.base import LLMProvider, ModelInfo
from schemas.message import LLMResponse, Message, ToolCall


class LMStudioProvider(LLMProvider):
    """
    LM Studio provider for running local models.
    Uses OpenAI-compatible API format.
    """

    name = "lmstudio"

    DEFAULT_MODELS = [
        "local-model",  # LM Studio uses the loaded model
    ]

    def __init__(
        self,
        model: str = "local-model",
        api_key: str | None = None,  # Not needed for local
        base_url: str = "http://localhost:1234/v1",
    ):
        self.model = model
        self.api_key = api_key or "lm-studio"  # Placeholder
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=300.0)  # Longer timeout for local

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def list_models(self) -> list[ModelInfo]:
        """Fetch loaded models from LM Studio."""
        try:
            response = self.client.get(f"{self.base_url}/models", headers=self._get_headers())
            response.raise_for_status()
            data = response.json()

            models = []
            for model in data.get("data", []):
                models.append(
                    ModelInfo(
                        id=model.get("id"),
                        name=model.get("id"),
                    )
                )

            return models if models else [ModelInfo(id="local-model", name="Local Model")]

        except Exception:
            return [ModelInfo(id="local-model", name="Local Model (LM Studio)")]

    def generate(
        self,
        messages: list[Message],
        tools: list | None = None,
        stream: bool = False,
    ) -> LLMResponse:
        # Format messages for LM Studio API
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

        # Format tools (if model supports it)
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

        response = self.client.post(
            f"{self.base_url}/chat/completions", headers=self._get_headers(), json=payload
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
