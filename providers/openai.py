import json
from typing import List, Optional
from openai import OpenAI

from schemas.message import Message, LLMResponse, ToolCall
from providers.base import LLMProvider

class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, model: str = "gpt-4o", api_key: Optional[str] = None):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def generate(
        self,
        messages: List[Message],
        tools: Optional[list] = None,
        stream: bool = False,
    ) -> LLMResponse:
        
        # Format messages for OpenAI
        formatted_messages = []
        for msg in messages:
            formatted_msg = {"role": msg.role, "content": msg.content}
            if msg.role == "tool":
                formatted_msg["tool_call_id"] = getattr(msg, 'tool_call_id', msg.name)
            formatted_messages.append(formatted_msg)
            
        # Format tools for OpenAI
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
                
        response = self.client.chat.completions.create(
            model=self.model,
            messages=formatted_messages,
            tools=formatted_tools,
            temperature=0.0
        )
        
        choice = response.choices[0]
        message = choice.message
        
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                # OpenAI returns arguments as a JSON string
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                
                tool_call = ToolCall(name=tc.function.name, arguments=args)
                tool_call.id = tc.id # Attach id for OpenAI context matching
                tool_calls.append(tool_call)
                
        # Handle case where assistant message has no content but has tool calls
        content = message.content if message.content else "Calling tool..."
                
        return LLMResponse(
            message=Message(role="assistant", content=content),
            tool_calls=tool_calls if tool_calls else None,
            raw=response
        )
