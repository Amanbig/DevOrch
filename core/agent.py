import json
from collections.abc import Callable

from core.executor import Executor
from core.modes import AgentMode, ModeManager
from core.planner import Planner
from core.sessions import SessionManager
from providers.base import LLMProvider
from schemas.message import Message, ToolCall
from utils.logger import get_console, print_info, print_success, print_warning

console = get_console()

SUMMARIZATION_PROMPT = """Please provide a concise summary of our conversation so far. Include:
1. The main topics we discussed
2. Key decisions or conclusions reached
3. Any important context or information that would be needed to continue this conversation
4. Current task status if any work is in progress

Keep the summary focused and under 500 words."""

PLAN_MODE_PROMPT = """You are in PLAN MODE. Before taking any actions:

1. First, analyze the user's request carefully
2. Create a clear, numbered plan of steps you will take
3. List each tool you plan to use and why
4. Present this plan to the user in a clear format like:

📋 **Plan:**
1. [Step description] - using [tool_name]
2. [Step description] - using [tool_name]
...

After presenting the plan, ask: "Should I proceed with this plan? (yes/no/modify)"

Do NOT execute any tools until the user approves the plan."""


class Agent:
    def __init__(
        self,
        provider: LLMProvider,
        planner: Planner,
        executor: Executor,
        tools: list,
        session_manager: SessionManager | None = None,
        on_session_continue: Callable[[str], None] | None = None,
        mode_manager: ModeManager | None = None,
    ):
        self.provider = provider
        self.planner = planner
        self.executor = executor
        self.tools = tools
        self.session_manager = session_manager
        self.on_session_continue = on_session_continue  # Callback when session continues
        self.mode_manager = mode_manager or ModeManager()
        self.history: list[Message] = []
        self._context_summary: str | None = None  # Summary from previous session
        self._awaiting_plan_approval: bool = False
        self._pending_plan_response: str | None = None

    def set_history(self, messages: list[Message]):
        """Set the conversation history (used when resuming a session)."""
        self.history = messages

    def set_context_summary(self, summary: str):
        """Set context summary from a previous session."""
        self._context_summary = summary

    def _display_tool_call(self, call: ToolCall):
        """Display a tool call in a compact, user-friendly format."""
        args = call.arguments

        # Build a clean summary based on tool type
        if call.name == "shell":
            cmd = args.get("command", "")
            # Shell command with subtle background
            console.print(f"  [dim]>[/dim] [on #1e2030][cyan]shell[/cyan] [bold]{cmd}[/bold][/]")

        elif call.name == "filesystem":
            action = args.get("action", "")
            path = args.get("path", "")
            content = args.get("content", "")

            if action == "write":
                lines = content.count("\n") + 1 if content else 0
                summary = f"[cyan]write[/cyan] {lines} lines to [bold]{path}[/bold]"
            elif action == "read":
                summary = f"[cyan]read[/cyan] [bold]{path}[/bold]"
            elif action == "list":
                summary = f"[cyan]list[/cyan] [bold]{path}[/bold]"
            else:
                summary = f"[cyan]{action}[/cyan] [bold]{path}[/bold]"

            console.print(f"  [dim]>[/dim] {summary}")

        elif call.name == "search":
            pattern = args.get("pattern", "")
            path = args.get("path", ".")
            console.print(f"  [dim]>[/dim] [cyan]search[/cyan] [bold]{pattern}[/bold] in {path}")

        elif call.name == "grep":
            pattern = args.get("pattern", "")
            path = args.get("path", ".")
            console.print(f"  [dim]>[/dim] [cyan]grep[/cyan] [bold]{pattern}[/bold] in {path}")

        elif call.name == "edit":
            path = args.get("path", "")
            console.print(f"  [dim]>[/dim] [cyan]edit[/cyan] [bold]{path}[/bold]")

        elif call.name == "task":
            # Task tool - don't show anything, the task panel will display
            pass

        elif call.name == "websearch":
            query = args.get("query", "")
            console.print(f"  [dim]>[/dim] [cyan]searching web[/cyan] [bold]{query}[/bold]")

        elif call.name == "webfetch":
            url = args.get("url", "")
            # Truncate long URLs
            display_url = url[:60] + "..." if len(url) > 60 else url
            console.print(f"  [dim]>[/dim] [cyan]fetching[/cyan] [bold]{display_url}[/bold]")

        elif call.name == "memory":
            action = args.get("action", "")
            name = args.get("name", "")
            query = args.get("query", "")
            if action == "save":
                console.print(f"  [dim]>[/dim] [cyan]saving memory[/cyan] [bold]{name}[/bold]")
            elif action == "search":
                console.print(f"  [dim]>[/dim] [cyan]searching memory[/cyan] [bold]{query}[/bold]")
            elif action == "list":
                console.print("  [dim]>[/dim] [cyan]listing memories[/cyan]")
            elif action == "delete":
                console.print(
                    f"  [dim]>[/dim] [cyan]deleting memory[/cyan] [bold]{args.get('filename', '')}[/bold]"
                )
            else:
                console.print(f"  [dim]>[/dim] [cyan]memory {action}[/cyan]")

        elif call.name.startswith("mcp_"):
            # MCP tool call
            console.print(f"  [dim]>[/dim] [#6a8aaa]MCP[/#6a8aaa] [cyan]{call.name}[/cyan]")

        else:
            # Generic fallback - show tool name and brief args
            brief_args = {
                k: (v[:50] + "..." if isinstance(v, str) and len(v) > 50 else v)
                for k, v in args.items()
            }
            console.print(f"  [dim]>[/dim] [cyan]{call.name}[/cyan] {brief_args}")

    def _display_tool_result(self, tool_name: str, result: str):
        """Display tool result in a compact, user-friendly format.

        The full result always goes to the LLM — this only controls
        what the USER sees in the terminal.
        """
        result_str = str(result)

        # Skip display entirely for these tools
        if tool_name == "task":
            return

        # ── Errors — always show ─────────────────────────────────────────
        if "Error:" in result_str or result_str.startswith("Error"):
            console.print(f"    [red]✗ {result_str[:300]}[/red]")
            return

        # ── File reads — never dump content, just show summary ───────────
        if tool_name == "filesystem":
            if "Successfully wrote" in result_str or "Successfully created" in result_str:
                console.print(f"    [green]✓[/green] [dim]{result_str[:100]}[/dim]")
            elif "] Lines " in result_str[:120]:
                # Extract header like "[README.md] Lines 1-200 of 488"
                header = result_str.split("\n", 1)[0]
                console.print(f"    [green]✓[/green] [dim]{header}[/dim]")
            else:
                lines = result_str.count("\n")
                console.print(f"    [green]✓[/green] [dim]Done ({lines} lines)[/dim]")
            return

        # ── Search/grep — just show match count ──────────────────────────
        if tool_name in ("search", "grep"):
            matches = [m for m in result_str.strip().split("\n") if m.strip()]
            console.print(f"    [green]✓[/green] [dim]Found {len(matches)} matches[/dim]")
            return

        # ── Web tools — show summary ─────────────────────────────────────
        if tool_name == "websearch":
            result_count = sum(
                1
                for line in result_str.strip().split("\n")
                if line.strip().startswith(("1.", "2.", "3.", "4.", "5."))
            )
            console.print(f"    [green]✓[/green] [dim]Found {result_count} web results[/dim]")
            return

        if tool_name == "webfetch":
            lines = result_str.count("\n")
            console.print(f"    [green]✓[/green] [dim]Fetched page ({lines} lines)[/dim]")
            return

        # ── Memory — show brief ──────────────────────────────────────────
        if tool_name == "memory":
            first_line = result_str.split("\n", 1)[0]
            console.print(f"    [green]✓[/green] [dim]{first_line[:80]}[/dim]")
            return

        # ── Shell output — truncate heavily ──────────────────────────────
        if result_str.startswith("STDOUT:") or result_str.startswith("STDERR:"):
            max_display = 200
            if len(result_str) > max_display:
                display_result = (
                    result_str[:max_display] + f"\n... ({result_str.count(chr(10))} total lines)"
                )
            else:
                display_result = result_str

            # Show output with subtle background
            for line in display_result.split("\n"):
                console.print(f"    [dim on #1a1a28]{line}[/]")
            return

        # ── Everything else — brief one-liner ────────────────────────────
        first_line = result_str.split("\n", 1)[0]
        if len(first_line) > 80:
            first_line = first_line[:80] + "..."
        console.print(f"    [green]✓[/green] [dim]{first_line}[/dim]")

    def _save_message(self, message: Message):
        """Save a message to history and session storage."""
        self.history.append(message)
        if self.session_manager:
            self.session_manager.save_message(message)

    def _generate_summary(self) -> str:
        """Generate a summary of the current conversation."""
        # Build messages for summarization (without tools)
        summary_messages = [
            Message(
                role="system", content="You are a helpful assistant that summarizes conversations."
            ),
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
            provider=self.provider.name, model=self.provider.model, summary=summary
        )

        print_info(f"Continued to new session: {new_session_id}")

        # Reset history with summary as context
        self.history = []
        self._context_summary = summary

        # Save a system message with the summary context
        context_message = Message(
            role="assistant",
            content=f"[Previous conversation summary]\n{summary}\n\n[Continuing conversation...]",
        )
        self._save_message(context_message)

        # Notify callback if set
        if self.on_session_continue:
            self.on_session_continue(new_session_id)

        return True

    def _handle_plan_approval(self, user_input: str) -> str | None:
        """Handle plan approval responses. Returns response or None to continue."""
        input_lower = user_input.strip().lower()

        if input_lower in ("yes", "y", "proceed", "go", "ok", "continue"):
            self._awaiting_plan_approval = False
            print_success("Plan approved! Executing...")
            # Switch to auto mode temporarily for this execution
            return None  # Continue with execution

        elif input_lower in ("no", "n", "cancel", "stop", "abort"):
            self._awaiting_plan_approval = False
            self._pending_plan_response = None
            return "Plan cancelled. What would you like me to do instead?"

        elif input_lower.startswith("modify") or input_lower.startswith("change"):
            self._awaiting_plan_approval = False
            # User wants to modify, treat the rest as new instructions
            modification = (
                user_input[6:].strip()
                if input_lower.startswith("modify")
                else user_input[6:].strip()
            )
            if modification:
                return self.run(f"Please modify the plan: {modification}", max_iterations=15)
            return "What changes would you like me to make to the plan?"

        else:
            # Treat as modification request
            return self.run(user_input, max_iterations=15)

    def run(self, user_input: str, max_iterations: int = 15):
        # Check if we're awaiting plan approval
        if self._awaiting_plan_approval:
            result = self._handle_plan_approval(user_input)
            if result is not None:
                return result
            # If None, continue with the pending execution

        # Check session limit before processing
        self._check_and_handle_session_limit()

        # Save user message
        user_message = Message(role="user", content=user_input)
        self._save_message(user_message)

        iteration = 0
        is_plan_mode = self.mode_manager.mode == AgentMode.PLAN
        plan_created = False

        while iteration < max_iterations:
            planned_messages = self.planner.plan(self.history)

            # Inject context summary if available
            if self._context_summary and iteration == 0:
                # Add summary context after system message
                for i, msg in enumerate(planned_messages):
                    if msg.role == "system":
                        context_msg = Message(
                            role="system",
                            content=f"\n\n[Previous conversation context]\n{self._context_summary}",
                        )
                        planned_messages.insert(i + 1, context_msg)
                        break

            # In plan mode, inject plan prompt on first iteration
            if is_plan_mode and iteration == 0 and not plan_created:
                for i, msg in enumerate(planned_messages):
                    if msg.role == "system":
                        plan_msg = Message(role="system", content=f"\n\n{PLAN_MODE_PROMPT}")
                        planned_messages.insert(i + 1, plan_msg)
                        break

            # Determine which tools to provide based on mode
            if is_plan_mode and not plan_created:
                # In planning phase, don't provide tools so LLM creates plan first
                tools_for_call = None
                status_msg = "[bold yellow]DevOrch is planning..."
            else:
                tools_for_call = [tool.schema() for tool in self.tools]
                status_msg = "[bold blue]DevOrch is thinking..."

            with console.status(status_msg, spinner="dots"):
                response = self.provider.generate(
                    planned_messages,
                    tools=tools_for_call,
                )

            # Save assistant message (include tool_calls in metadata for providers like Mistral)
            if response.tool_calls:
                # Store tool_calls info in metadata for conversation reconstruction
                tool_calls_data = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in response.tool_calls
                ]
                response.message.metadata = response.message.metadata or {}
                response.message.metadata["tool_calls"] = tool_calls_data

            self._save_message(response.message)

            # In plan mode, check if this is a plan response
            if is_plan_mode and not plan_created and not response.tool_calls:
                plan_created = True
                self._awaiting_plan_approval = True
                self._pending_plan_response = response.message.content
                # Check session limit after response
                self._check_and_handle_session_limit()
                return response.message.content

            if not response.tool_calls:
                # The LLM didn't call any tools, so we have a final answer
                # Check session limit after response
                self._check_and_handle_session_limit()
                return response.message.content

            for call in response.tool_calls:
                # Display tool call in a nice panel
                self._display_tool_call(call)

                # Execute without spinner - the spinner blocks input for permission prompts
                result = self.executor.execute(call.name, call.arguments)

                # Display result in a nice panel
                self._display_tool_result(call.name, result)

                # Save tool result message
                tool_message = Message(
                    role="tool", content=str(result), name=call.name, tool_call_id=call.id
                )
                self._save_message(tool_message)

            iteration += 1

        return "Error: Maximum iterations reached without a final answer."
