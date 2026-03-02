"""
Together AI Provider - Open source models at scale
https://together.ai/
"""

import json
from typing import List, Optional
import httpx

from schemas.message import Message, LLMResponse, ToolCall
from providers.base import LLMProvider, ModelInfo


class TogetherProvider(LLMProvider):
    """
    Together AI provider for open source models.
    Supports Llama, Mistral, Code Llama, and more.
    """
    name = "together"

    DEFAULT_MODELS = [
        "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
        "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        "mistralai/Mixtral-8x22B-Instruct-v0.1",
        "mistralai/Mistral-7B-Instruct-v0.3",
        "Qwen/Qwen2-72B-Instruct",
        "deepseek-ai/deepseek-coder-33b-instruct",
    ]

    BASE_URL = "https://api.together.xyz/v1"

    def __init__(
        self,
        model: str = "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        api_key: Optional[str] = None,
    ):
        self.model = model
        self.api_key = api_key
        self.client = httpx.Client(timeout=120.0)

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def list_models(self) -> List[ModelInfo]:
        """Fetch available models from Together API."""
        try:
            response = self.client.get(
                f"{self.BASE_URL}/models",
                headers=self._get_headers()
            )
            response.raise_for_status()
            data = response.json()

            models = []
            # Filter to chat/instruct models
            for model in data:
                model_id = model.get("id", "")
                model_type = model.get("type", "")
                if "chat" in model_type.lower() or "instruct" in model_id.lower():
                    models.append(ModelInfo(
                        id=model_id,
                        name=model.get("display_name", model_id),
                        context_length=model.get("context_length"),
                    ))

            models.sort(key=lambda m: m.name)
            return models[:50] if models else [ModelInfo(id=m, name=m) for m in self.DEFAULT_MODELS]

        except Exception:
            return [ModelInfo(id=m, name=m) for m in self.DEFAULT_MODELS]

    def generate(
        self,
        messages: List[Message],
        tools: Optional[list] = None,
        stream: bool = False,
    ) -> LLMResponse:
        # Format messages for Together API
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

        # Format tools
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
