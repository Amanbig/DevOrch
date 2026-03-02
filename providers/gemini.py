from typing import List, Optional, Dict, Any

import google.generativeai as genai
from google.generativeai.types import FunctionDeclaration, Tool as GeminiTool

from schemas.message import Message, LLMResponse, ToolCall
from providers.base import LLMProvider


class GeminiProvider(LLMProvider):
    """Google Gemini provider with function calling support."""

    name = "gemini"

    def __init__(self, model: str = "gemini-1.5-pro", api_key: Optional[str] = None):
        if api_key:
            genai.configure(api_key=api_key)
        self.model_name = model
        self.model = model

    def generate(
        self,
        messages: List[Message],
        tools: Optional[list] = None,
        stream: bool = False,
    ) -> LLMResponse:
        # Format tools for Gemini
        gemini_tools = None
        if tools:
            function_declarations = []
            for tool in tools:
                params = tool.get("parameters", {"type": "object", "properties": {}})
                # Convert parameters to Gemini format
                gemini_params = self._convert_params(params)
                function_declarations.append(
                    FunctionDeclaration(
                        name=tool["name"],
                        description=tool["description"],
                        parameters=gemini_params
                    )
                )
            gemini_tools = [GeminiTool(function_declarations=function_declarations)]

        # Build conversation history
        system_instruction = None
        history = []
        pending_function_responses = []

        for msg in messages:
            if msg.role == "system":
                system_instruction = msg.content
            elif msg.role == "user":
                # If we have pending function responses, add them first
                if pending_function_responses:
                    history.append({
                        "role": "user",
                        "parts": pending_function_responses
                    })
                    pending_function_responses = []
                history.append({"role": "user", "parts": [msg.content]})
            elif msg.role == "assistant":
                # Check for function call metadata
                if msg.metadata and msg.metadata.get("function_calls"):
                    parts = []
                    if msg.content and msg.content != "Calling tool...":
                        parts.append(msg.content)
                    for fc in msg.metadata["function_calls"]:
                        parts.append(genai.protos.Part(
                            function_call=genai.protos.FunctionCall(
                                name=fc["name"],
                                args=fc["args"]
                            )
                        ))
                    history.append({"role": "model", "parts": parts})
                else:
                    history.append({"role": "model", "parts": [msg.content]})
            elif msg.role == "tool":
                # Tool results in Gemini use FunctionResponse
                pending_function_responses.append(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=msg.name,
                            response={"result": msg.content}
                        )
                    )
                )

        # If we have remaining function responses, add them
        if pending_function_responses:
            history.append({
                "role": "user",
                "parts": pending_function_responses
            })

        # Create model with system instruction if present
        model_kwargs = {}
        if system_instruction:
            model_kwargs["system_instruction"] = system_instruction

        model = genai.GenerativeModel(self.model_name, **model_kwargs)

        # Start chat with history (excluding last message)
        chat_history = history[:-1] if len(history) > 1 else []
        chat = model.start_chat(history=chat_history)

        # Get the last message content
        if history:
            last_parts = history[-1].get("parts", [])
            if last_parts:
                last_message = last_parts[0] if isinstance(last_parts[0], str) else last_parts
            else:
                last_message = ""
        else:
            last_message = ""

        # Send message
        try:
            response = chat.send_message(
                last_message,
                tools=gemini_tools
            )
        except Exception as e:
            # If tools fail, try without them
            if gemini_tools and "tool" in str(e).lower():
                response = chat.send_message(last_message)
            else:
                raise

        # Parse response
        tool_calls = []
        text_content = ""
        function_call_metadata = []

        for part in response.parts:
            if hasattr(part, "text") and part.text:
                text_content += part.text
            if hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                # Convert args to dict
                args = dict(fc.args) if fc.args else {}
                tool_call = ToolCall(
                    name=fc.name,
                    arguments=args,
                    id=f"gemini_{fc.name}_{len(tool_calls)}"  # Gemini doesn't provide IDs
                )
                tool_calls.append(tool_call)
                function_call_metadata.append({
                    "name": fc.name,
                    "args": args
                })

        content = text_content if text_content else "Calling tool..."

        # Store function calls in metadata for history reconstruction
        metadata = {"function_calls": function_call_metadata} if function_call_metadata else None

        return LLMResponse(
            message=Message(role="assistant", content=content, metadata=metadata),
            tool_calls=tool_calls if tool_calls else None,
            raw=response
        )

    def _convert_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Convert JSON Schema parameters to Gemini format."""
        # Gemini uses similar format but may need type uppercase conversion
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
