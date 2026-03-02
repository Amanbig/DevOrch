from typing import List, Optional, Dict, Any

from google import genai
from google.genai import types

from schemas.message import Message, LLMResponse, ToolCall
from providers.base import LLMProvider, ModelInfo


class GeminiProvider(LLMProvider):
    """Google Gemini provider with function calling support using the new google.genai SDK."""

    name = "gemini"

    DEFAULT_MODELS = [
        "gemini-2.0-flash",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
        "gemini-pro",
    ]

    def __init__(self, model: str = "gemini-2.0-flash", api_key: Optional[str] = None):
        self.model_name = model
        self.model = model
        self.client = genai.Client(api_key=api_key)

    def list_models(self) -> List[ModelInfo]:
        """Fetch available models from Gemini API."""
        try:
            models = []
            for m in self.client.models.list():
                # Filter for models that support content generation
                if hasattr(m, 'supported_actions') and 'generateContent' in m.supported_actions:
                    model_id = m.name.replace("models/", "") if m.name.startswith("models/") else m.name
                    models.append(ModelInfo(
                        id=model_id,
                        name=getattr(m, 'display_name', model_id),
                        description=getattr(m, 'description', ''),
                    ))
            return models if models else [ModelInfo(id=m, name=m) for m in self.DEFAULT_MODELS]
        except Exception:
            return [ModelInfo(id=m, name=m) for m in self.DEFAULT_MODELS]

    def generate(
        self,
        messages: List[Message],
        tools: Optional[list] = None,
        stream: bool = False,
    ) -> LLMResponse:
        # Build contents list for the API
        contents = []
        system_instruction = None

        for msg in messages:
            if msg.role == "system":
                system_instruction = msg.content
            elif msg.role == "user":
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=msg.content)]
                ))
            elif msg.role == "assistant":
                # Check for function call metadata
                if msg.metadata and msg.metadata.get("function_calls"):
                    parts = []
                    if msg.content and msg.content != "Calling tool...":
                        parts.append(types.Part.from_text(text=msg.content))
                    for fc in msg.metadata["function_calls"]:
                        parts.append(types.Part.from_function_call(
                            name=fc["name"],
                            args=fc["args"]
                        ))
                    contents.append(types.Content(role="model", parts=parts))
                else:
                    contents.append(types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=msg.content)]
                    ))
            elif msg.role == "tool":
                # Tool results use function_response
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_function_response(
                        name=msg.name,
                        response={"result": msg.content}
                    )]
                ))

        # Build tools configuration
        gemini_tools = None
        if tools:
            function_declarations = []
            for tool in tools:
                params = tool.get("parameters", {"type": "object", "properties": {}})
                gemini_params = self._convert_params(params)
                function_declarations.append(types.FunctionDeclaration(
                    name=tool["name"],
                    description=tool["description"],
                    parameters=gemini_params
                ))
            gemini_tools = [types.Tool(function_declarations=function_declarations)]

        # Build config
        config_kwargs = {}
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if gemini_tools:
            config_kwargs["tools"] = gemini_tools
            # Disable automatic function calling - we handle it ourselves
            config_kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
                disable=True
            )

        config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        # Generate response
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config
            )
        except Exception as e:
            # If tools fail, try without them
            if gemini_tools and "tool" in str(e).lower():
                config_no_tools = types.GenerateContentConfig(
                    system_instruction=system_instruction
                ) if system_instruction else None
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=config_no_tools
                )
            else:
                raise

        # Parse response
        tool_calls = []
        text_content = ""
        function_call_metadata = []

        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    text_content += part.text
                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    # Convert args to dict
                    args = dict(fc.args) if fc.args else {}
                    tool_call = ToolCall(
                        name=fc.name,
                        arguments=args,
                        id=f"gemini_{fc.name}_{len(tool_calls)}"
                    )
                    tool_calls.append(tool_call)
                    function_call_metadata.append({
                        "name": fc.name,
                        "args": args
                    })

        content = text_content if text_content else ("Calling tool..." if tool_calls else "")

        # Store function calls in metadata for history reconstruction
        metadata = {"function_calls": function_call_metadata} if function_call_metadata else None

        return LLMResponse(
            message=Message(role="assistant", content=content, metadata=metadata),
            tool_calls=tool_calls if tool_calls else None,
            raw=response
        )

    def _convert_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Convert JSON Schema parameters to Gemini format."""
        result = {}

        if "type" in params:
            result["type"] = params["type"].upper()

        if "properties" in params:
            result["properties"] = {}
            for key, value in params["properties"].items():
                prop = {}
                if "type" in value:
                    prop["type"] = value["type"].upper()
                if "description" in value:
                    prop["description"] = value["description"]
                if "enum" in value:
                    prop["enum"] = value["enum"]
                result["properties"][key] = prop

        if "required" in params:
            result["required"] = params["required"]

        return result
