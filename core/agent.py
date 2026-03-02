from typing import List, Optional, Callable

from schemas.message import Message
from providers.base import LLMProvider
from core.planner import Planner
from core.executor import Executor
from core.sessions import SessionManager
from utils.logger import get_console, print_panel, print_info, print_warning
import json

console = get_console()

SUMMARIZATION_PROMPT = """Please provide a concise summary of our conversation so far. Include:
1. The main topics we discussed
2. Key decisions or conclusions reached
3. Any important context or information that would be needed to continue this conversation
4. Current task status if any work is in progress

Keep the summary focused and under 500 words."""


class Agent:
    def __init__(
        self,
        provider: LLMProvider,
        planner: Planner,
        executor: Executor,
        tools: list,
        session_manager: Optional[SessionManager] = None,
        on_session_continue: Optional[Callable[[str], None]] = None,
    ):
        self.provider = provider
        self.planner = planner
        self.executor = executor
        self.tools = tools
        self.session_manager = session_manager
        self.on_session_continue = on_session_continue  # Callback when session continues
        self.history: List[Message] = []
        self._context_summary: Optional[str] = None  # Summary from previous session

    def set_history(self, messages: List[Message]):
        """Set the conversation history (used when resuming a session)."""
        self.history = messages

    def set_context_summary(self, summary: str):
        """Set context summary from a previous session."""
        self._context_summary = summary

    def _save_message(self, message: Message):
        """Save a message to history and session storage."""
        self.history.append(message)
        if self.session_manager:
            self.session_manager.save_message(message)

    def _generate_summary(self) -> str:
        """Generate a summary of the current conversation."""
        # Build messages for summarization (without tools)
        summary_messages = [
            Message(role="system", content="You are a helpful assistant that summarizes conversations."),
        ]

        # Add conversation history (simplified)
        for msg in self.history:
            if msg.role in ("user", "assistant"):
                summary_messages.append(msg)

        summary_messages.append(Message(role="user", content=SUMMARIZATION_PROMPT))

        # Generate summary without tools
        with console.status("[bold yellow]Summarizing conversation...", spinner="dots"):
            response = self.provider.generate(summary_messages, tools=None)

        return response.message.content

    def _check_and_handle_session_limit(self) -> bool:
        """Check if session needs summarization and handle it. Returns True if continued."""
        if not self.session_manager:
            return False

        if not self.session_manager.should_summarize():
            return False

        print_warning(f"Session approaching limit ({self.session_manager.message_limit} messages)")
        print_info("Summarizing conversation and creating continuation session...")

        # Generate summary
        summary = self._generate_summary()

        # Create continuation session
        new_session_id = self.session_manager.create_continuation_session(
            provider=self.provider.name,
            model=self.provider.model,
            summary=summary
        )

        print_info(f"Continued to new session: {new_session_id}")

        # Reset history with summary as context
        self.history = []
        self._context_summary = summary

        # Save a system message with the summary context
        context_message = Message(
            role="assistant",
            content=f"[Previous conversation summary]\n{summary}\n\n[Continuing conversation...]"
        )
        self._save_message(context_message)

        # Notify callback if set
        if self.on_session_continue:
            self.on_session_continue(new_session_id)

        return True

    def run(self, user_input: str, max_iterations: int = 15):
        # Check session limit before processing
        self._check_and_handle_session_limit()

        # Save user message
        user_message = Message(role="user", content=user_input)
        self._save_message(user_message)

        iteration = 0
        while iteration < max_iterations:
            planned_messages = self.planner.plan(self.history)

            # Inject context summary if available
            if self._context_summary and iteration == 0:
                # Add summary context after system message
                for i, msg in enumerate(planned_messages):
                    if msg.role == "system":
                        context_msg = Message(
                            role="system",
                            content=f"\n\n[Previous conversation context]\n{self._context_summary}"
                        )
                        planned_messages.insert(i + 1, context_msg)
                        break

            with console.status("[bold blue]DevPilot is thinking...", spinner="dots"):
                response = self.provider.generate(
                    planned_messages,
                    tools=[tool.schema() for tool in self.tools],
                )

            # Save assistant message
            self._save_message(response.message)

            if not response.tool_calls:
                # The LLM didn't call any tools, so we have a final answer
                # Check session limit after response
                self._check_and_handle_session_limit()
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
