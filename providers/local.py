import json

import httpx
from openai import OpenAI

from providers.base import LLMProvider, ModelInfo
from schemas.message import LLMResponse, Message, ToolCall


class LocalProvider(LLMProvider):
    """Local LLM provider using Ollama's OpenAI-compatible API."""

    name = "local"

    # Models known to support function calling well
    TOOL_CAPABLE_MODELS = [
        "llama3.1",
        "llama3.2",
        "qwen2.5:7b",
        "qwen2.5:14b",
        "qwen2.5:32b",
        "qwen2.5-coder",
        "mistral",
        "mixtral",
        "command-r",
        "firefunction",
    ]

    DEFAULT_MODELS = [
        "llama3.1",
        "llama3.2",
        "llama3",
        "codellama",
        "mistral",
        "mixtral",
        "gemma2",
        "qwen2.5",
        "qwen2.5-coder",
        "deepseek-coder-v2",
    ]

    def __init__(
        self,
        model: str | None = None,
        base_url: str = "http://localhost:11434/v1",
        api_key: str | None = None,
    ):
        self.base_url = base_url

        # Ollama's OpenAI-compatible endpoint
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key or "ollama",  # Placeholder, Ollama ignores this
        )

        # Auto-detect model if not specified
        if model:
            self.model = model
        else:
            self.model = self._detect_default_model()

        # Track if we've warned about tool capability
        self._tool_warning_shown = False

    def _detect_default_model(self) -> str:
        """Auto-detect the first available model from Ollama."""
        try:
            ollama_base = self.base_url.replace("/v1", "")
            response = httpx.get(f"{ollama_base}/api/tags", timeout=5.0)
            response.raise_for_status()
            data = response.json()

            models = data.get("models", [])
            if models:
                # Return the first available model
                return models[0].get("name", "llama3")

        except Exception:
            pass

        # Fallback to first default model
        return self.DEFAULT_MODELS[0]

    def _is_tool_capable(self, model_name: str) -> bool:
        """Check if a model is known to support function calling."""
        model_lower = model_name.lower()
        for capable in self.TOOL_CAPABLE_MODELS:
            if capable in model_lower:
                return True
        # Small models (under 3B) generally don't support tools well
        if ":0.5b" in model_lower or ":1b" in model_lower or ":2b" in model_lower:
            return False
        return True  # Assume capable for unknown larger models

    def list_models(self) -> list[ModelInfo]:
        """Fetch models from local Ollama instance."""
        try:
            # Ollama API endpoint for listing models
            ollama_base = self.base_url.replace("/v1", "")
            response = httpx.get(f"{ollama_base}/api/tags", timeout=5.0)
            response.raise_for_status()
            data = response.json()

            models = []
            for model in data.get("models", []):
                name = model.get("name")
                tool_note = "" if self._is_tool_capable(name) else " (no tool support)"
                models.append(
                    ModelInfo(
                        id=name,
                        name=name,
                        description=tool_note if tool_note else None,
                    )
                )

            return models if models else [ModelInfo(id=m, name=m) for m in self.DEFAULT_MODELS]

        except Exception:
            return [ModelInfo(id=m, name=m + " (not pulled)") for m in self.DEFAULT_MODELS]

    def generate(
        self,
        messages: list[Message],
        tools: list | None = None,
        stream: bool = False,
    ) -> LLMResponse:
        # Format messages (same as OpenAI)
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

        # Format tools (same as OpenAI)
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

        # Warn if model may not support tools
        if (
            formatted_tools
            and not self._tool_warning_shown
            and not self._is_tool_capable(self.model)
        ):
            import sys

            print(f"\n⚠️  Warning: {self.model} may not support function calling.", file=sys.stderr)
            print(
                "   For best results, use a larger model like llama3.1, qwen2.5:7b, or mistral.",
                file=sys.stderr,
            )
            print("   Run: ollama pull llama3.1\n", file=sys.stderr)
            self._tool_warning_shown = True

        # Try with tools first, fall back to without if model doesn't support them
        try:
            kwargs = {"model": self.model, "messages": formatted_messages, "temperature": 0.0}
            if formatted_tools:
                kwargs["tools"] = formatted_tools

            response = self.client.chat.completions.create(**kwargs)
        except Exception as e:
            error_str = str(e).lower()
            # Retry without tools if the model doesn't support function calling
            if formatted_tools and ("tool" in error_str or "function" in error_str):
                response = self.client.chat.completions.create(
                    model=self.model, messages=formatted_messages, temperature=0.0
                )
            else:
                raise

        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                tool_call = ToolCall(name=tc.function.name, arguments=args, id=tc.id)
                tool_calls.append(tool_call)

        content = message.content if message.content else "Calling tool..."

        return LLMResponse(
            message=Message(role="assistant", content=content),
            tool_calls=tool_calls if tool_calls else None,
            raw=response,
        )
