from typing import List, Optional

from schemas.message import Message
from providers.base import LLMProvider
from core.planner import Planner
from core.executor import Executor
from core.sessions import SessionManager
from utils.logger import get_console, print_panel
import json

console = get_console()


class Agent:
    def __init__(
        self,
        provider: LLMProvider,
        planner: Planner,
        executor: Executor,
        tools: list,
        session_manager: Optional[SessionManager] = None,
    ):
        self.provider = provider
        self.planner = planner
        self.executor = executor
        self.tools = tools
        self.session_manager = session_manager
        self.history: List[Message] = []

    def set_history(self, messages: List[Message]):
        """Set the conversation history (used when resuming a session)."""
        self.history = messages

    def _save_message(self, message: Message):
        """Save a message to history and session storage."""
        self.history.append(message)
        if self.session_manager:
            self.session_manager.save_message(message)

    def run(self, user_input: str, max_iterations: int = 15):
        # Save user message
        user_message = Message(role="user", content=user_input)
        self._save_message(user_message)

        iteration = 0
        while iteration < max_iterations:
            planned_messages = self.planner.plan(self.history)

            with console.status("[bold blue]DevPilot is thinking...", spinner="dots"):
                response = self.provider.generate(
                    planned_messages,
                    tools=[tool.schema() for tool in self.tools],
                )

            # Save assistant message
            self._save_message(response.message)

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
                print_panel(snippet, title="Tool Result", border_style="green")

                # Save tool result message
                tool_message = Message(
                    role="tool",
                    content=str(result),
                    name=call.name,
                    tool_call_id=call.id
                )
                self._save_message(tool_message)

            iteration += 1

        return "Error: Maximum iterations reached without a final answer."
