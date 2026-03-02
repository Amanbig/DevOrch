import json
from typing import List, Optional
import httpx

from openai import OpenAI

from schemas.message import Message, LLMResponse, ToolCall
from providers.base import LLMProvider, ModelInfo


class LocalProvider(LLMProvider):
    """Local LLM provider using Ollama's OpenAI-compatible API."""

    name = "local"

    DEFAULT_MODELS = [
        "llama3.1",
        "llama3",
        "llama2",
        "codellama",
        "mistral",
        "mixtral",
        "gemma2",
        "qwen2",
        "deepseek-coder-v2",
    ]

    def __init__(
        self,
        model: str = "llama3",
        base_url: str = "http://localhost:11434/v1",
        api_key: Optional[str] = None
    ):
        # Ollama's OpenAI-compatible endpoint
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key or "ollama"  # Placeholder, Ollama ignores this
        )
        self.model = model
        self.base_url = base_url

    def list_models(self) -> List[ModelInfo]:
        """Fetch models from local Ollama instance."""
        try:
            # Ollama API endpoint for listing models
            ollama_base = self.base_url.replace("/v1", "")
            response = httpx.get(f"{ollama_base}/api/tags", timeout=5.0)
            response.raise_for_status()
            data = response.json()

            models = []
            for model in data.get("models", []):
                models.append(ModelInfo(
                    id=model.get("name"),
                    name=model.get("name"),
                ))

            return models if models else [ModelInfo(id=m, name=m) for m in self.DEFAULT_MODELS]

        except Exception:
            return [ModelInfo(id=m, name=m + " (not pulled)") for m in self.DEFAULT_MODELS]

    def generate(
        self,
        messages: List[Message],
        tools: Optional[list] = None,
        stream: bool = False,
    ) -> LLMResponse:
        # Format messages (same as OpenAI)
        formatted_messages = []
        for msg in messages:
            formatted_msg = {"role": msg.role, "content": msg.content}
            if msg.role == "tool":
                formatted_msg["tool_call_id"] = msg.tool_call_id or msg.name
            formatted_messages.append(formatted_msg)

        # Format tools (same as OpenAI)
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

        # Try with tools first, fall back to without if model doesn't support them
        try:
            kwargs = {
                "model": self.model,
                "messages": formatted_messages,
                "temperature": 0.0
            }
            if formatted_tools:
                kwargs["tools"] = formatted_tools

            response = self.client.chat.completions.create(**kwargs)
        except Exception as e:
            error_str = str(e).lower()
            # Retry without tools if the model doesn't support function calling
            if formatted_tools and ("tool" in error_str or "function" in error_str):
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=formatted_messages,
                    temperature=0.0
                )
            else:
                raise

        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                tool_call = ToolCall(
                    name=tc.function.name,
                    arguments=args,
                    id=tc.id
                )
                tool_calls.append(tool_call)

        content = message.content if message.content else "Calling tool..."

        return LLMResponse(
            message=Message(role="assistant", content=content),
            tool_calls=tool_calls if tool_calls else None,
            raw=response
        )
