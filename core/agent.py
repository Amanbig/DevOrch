from typing import List

from schemas.message import Message
from providers.base import LLMProvider
from core.planner import Planner
from core.executor import Executor


from rich.console import Console
from rich.panel import Panel
import json

console = Console()

class Agent:
    def __init__(
        self,
        provider: LLMProvider,
        planner: Planner,
        executor: Executor,
        tools: list,
    ):
        self.provider = provider
        self.planner = planner
        self.executor = executor
        self.tools = tools
        self.history: List[Message] = []

    def run(self, user_input: str, max_iterations: int = 15):
        self.history.append(Message(role="user", content=user_input))

        iteration = 0
        while iteration < max_iterations:
            planned_messages = self.planner.plan(self.history)

            with console.status("[bold blue]DevPilot is thinking...", spinner="dots"):
                response = self.provider.generate(
                    planned_messages,
                    tools=[tool.schema() for tool in self.tools],
                )

            self.history.append(response.message)

            if not response.tool_calls:
                # The LLM didn't call any tools, so we have a final answer
                return response.message.content

            for call in response.tool_calls:
                args_str = json.dumps(call.arguments)
                console.print(f"[bold magenta]🛠️  Tool Call:[/bold magenta] {call.name}({args_str})")
                
                with console.status(f"[bold cyan]Executing {call.name}...", spinner="bouncingBar"):
                    result = self.executor.execute(call.name, call.arguments)

                # Show a snippet of the result
                snippet = str(result)[:200] + ("..." if len(str(result)) > 200 else "")
                console.print(Panel(snippet, title="Tool Result", border_style="green"))

                self.history.append(
                    Message(
                        role="tool",
                        content=str(result),
                        name=call.name,
                        tool_call_id=getattr(call, 'id', None) # If the provider gives tool call IDs
                    )
                )
            
            iteration += 1

        return "Error: Maximum iterations reached without a final answer."