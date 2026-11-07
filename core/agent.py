import json
from collections.abc import Callable

from core.context import ContextManager
from core.executor import Executor
from core.images import prune_old_images
from core.loop_detector import LoopDetector, LoopSeverity
from core.model_limits import ModelLimits
from core.model_limits import parse_overrides as parse_window_overrides
from core.modes import AgentMode, ModeManager
from core.planner import Planner
from core.pricing import CostTracker
from core.retry import call_with_retry
from core.retry import describe as describe_error
from core.sessions import SessionManager
from providers.base import LLMProvider, extract_token_usage, response_was_truncated
from schemas.message import ImageData, Message, TokenUsage, ToolCall
from utils.logger import get_console, print_info, print_success, print_warning
from utils.streaming import StreamRenderer
from utils.tool_display import call_line, result_lines

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


INTERRUPTED_MESSAGE = "Interrupted. You can keep going; /undo reverts this turn's file changes."
INTERRUPTED_NOTE = "[The user interrupted this turn before it finished.]"


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
        context_manager: ContextManager | None = None,
        loop_detector: LoopDetector | None = None,
    ):
        self.planner = planner
        self.executor = executor
        self.tools = tools
        self.session_manager = session_manager
        self.on_session_continue = on_session_continue  # Callback when session continues
        self.mode_manager = mode_manager or ModeManager()
        # A context manager we create ourselves follows the model's context window; one the caller
        # passed in keeps the budgets it was given.
        self._auto_budget = context_manager is None
        self.context_manager = context_manager or ContextManager()
        self.provider = provider
        self.loop_detector = loop_detector or LoopDetector()
        self.last_turn_usage: TokenUsage | None = None
        # Image payloads older than this many image messages are replaced by a text note
        self.keep_recent_images = 2
        # Render model text live as it streams (interactive use); off for ask/run/json output
        self.stream_output = False
        self.last_run_interrupted = False
        self.retry_attempts = 3  # retries after a transient API error (so up to 4 calls)
        self.retry_base_delay = 1.0
        self.costs = CostTracker()
        self.last_turn_cost: float | None = None
        self.history: list[Message] = []
        self._context_summary: str | None = None  # Summary from previous session

    @property
    def provider(self) -> LLMProvider:
        return self._provider

    @provider.setter
    def provider(self, value: LLMProvider) -> None:
        """Switching provider or model (``/model``, ``/provider``) also retunes the history budget."""
        self._provider = value
        if getattr(self, "_auto_budget", False):
            self.context_manager.configure_for(value.name, value.model)

    def set_context_overrides(self, raw_windows) -> None:
        """Apply ``context_windows:`` overrides from config, then retune the budget for this model."""
        self.context_manager.limits = ModelLimits(parse_window_overrides(raw_windows))
        if self._auto_budget:
            self.context_manager.configure_for(self.provider.name, self.provider.model)

    def set_history(self, messages: list[Message]):
        """Set the conversation history (used when resuming a session)."""
        self.history = messages

    def set_context_summary(self, summary: str | None):
        """Set context summary from a previous session."""
        self._context_summary = summary

    def _display_tool_call(self, call: ToolCall):
        """Display a tool call in a compact, user-friendly format."""
        line = call_line(call.name, call.arguments)
        if line is not None:
            console.print(line)

    def _display_tool_result(self, tool_name: str, result: str, elapsed: float | None = None):
        """Display a tool result compactly. The full result always goes to the LLM."""
        for line in result_lines(tool_name, result, elapsed):
            console.print(line)

    def _call_model(self, messages: list[Message], tools: list | None, status_msg: str):
        """One model call: streamed or not, retried on transient API errors, and checked for truncation."""
        if self.stream_output and getattr(self.provider, "supports_streaming", False):
            shown: dict = {"text": "", "renderer": None}

            def attempt():
                with StreamRenderer(console, status_msg) as renderer:
                    try:
                        return self.provider.generate(messages, tools=tools, on_text=renderer.write)
                    finally:
                        shown["text"], shown["renderer"] = renderer.text, renderer

            # once text has been shown, a retry would repeat it, so only retry before that
            response = self._generate_with_retry(attempt, can_retry=lambda: not shown["text"])
            shown["renderer"].finish(is_final_answer=not response.tool_calls)
        else:

            def attempt():
                with console.status(status_msg, spinner="dots"):
                    return self.provider.generate(messages, tools=tools)

            response = self._generate_with_retry(attempt)
        self._warn_if_truncated(response)
        return response

    def _generate_with_retry(self, attempt, can_retry=lambda: True):
        """Run one model call, retrying rate limits, overloads and dropped connections with backoff."""

        def announce(n, total, delay, exc):
            print_warning(f"{describe_error(exc)}. Retrying in {delay:.0f}s ({n}/{total})...")

        return call_with_retry(
            attempt,
            max_retries=self.retry_attempts,
            base_delay=self.retry_base_delay,
            on_retry=announce,
            can_retry=can_retry,
        )

    @staticmethod
    def _warn_if_truncated(response) -> None:
        if response_was_truncated(getattr(response, "raw", None)):
            print_warning(
                "The reply was cut off by the model's output limit. Ask it to continue, or to do "
                "this in smaller steps."
            )

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

    def _awaiting_plan_approval(self) -> bool:
        """True when a plan has been shown but not yet approved or rejected."""
        plan = self.mode_manager.current_plan
        return plan is not None and not plan.approved

    def _handle_plan_approval(self, user_input: str) -> str | None:
        """Handle plan approval responses. Returns a reply string or None to proceed."""
        input_lower = user_input.strip().lower()

        if input_lower in ("yes", "y", "proceed", "go", "ok", "continue"):
            self.mode_manager.approve_plan()
            print_success("Plan approved! Executing...")
            return None  # Signal: continue with execution

        if input_lower in ("no", "n", "cancel", "stop", "abort"):
            self.mode_manager.clear_plan()
            return "Plan cancelled. What would you like me to do instead?"

        # "modify ..." or "change ..." — treat the rest as new instructions
        if input_lower.startswith(("modify", "change")):
            self.mode_manager.clear_plan()
            rest = user_input.split(None, 1)[1] if len(user_input.split(None, 1)) > 1 else ""
            if rest:
                return self.run(f"Please modify the plan: {rest}", max_iterations=15)
            return "What changes would you like me to make to the plan?"

        # Anything else — treat as a modification request
        self.mode_manager.clear_plan()
        return self.run(user_input, max_iterations=15)

    def run(
        self,
        user_input: str,
        max_iterations: int = 15,
        images: list[ImageData] | None = None,
    ):
        """Run one user turn. Ctrl+C cancels just this turn: history is repaired so the
        conversation stays valid, ``last_run_interrupted`` is set, and the session continues."""
        self.last_run_interrupted = False
        try:
            return self._run(user_input, max_iterations, images)
        except KeyboardInterrupt:
            self._repair_after_interrupt()
            self.last_run_interrupted = True
            return INTERRUPTED_MESSAGE

    def _repair_after_interrupt(self) -> None:
        """Leave history in a state every provider accepts after a mid-turn cancel.

        Providers require each assistant tool call to be followed by a tool result. If the turn
        was cancelled part-way through a batch of tool calls, answer the missing ones with an
        error result, then close the turn with a short assistant note so the next user message
        starts cleanly. Nothing is deleted, so stored sessions stay consistent with memory.
        """
        last_assistant = next(
            (
                i
                for i in range(len(self.history) - 1, -1, -1)
                if self.history[i].role == "assistant"
            ),
            None,
        )
        if last_assistant is not None:
            calls = (self.history[last_assistant].metadata or {}).get("tool_calls") or []
            answered = sum(1 for m in self.history[last_assistant + 1 :] if m.role == "tool")
            for call in calls[answered:]:
                fn = call.get("function", {})
                self._save_message(
                    Message(
                        role="tool",
                        content="Error: cancelled by the user before this tool finished.",
                        name=fn.get("name"),
                        tool_call_id=call.get("id"),
                    )
                )
        if self.history and self.history[-1].role in ("user", "tool"):
            self._save_message(Message(role="assistant", content=INTERRUPTED_NOTE))

    def _run(
        self,
        user_input: str,
        max_iterations: int = 15,
        images: list[ImageData] | None = None,
    ):
        if images and not getattr(self.provider, "supports_images", False):
            print_warning(
                f"{self.provider.name} does not support image input here; "
                f"sending text only ({len(images)} image(s) dropped)."
            )
            images = None

        is_plan_mode = self.mode_manager.mode == AgentMode.PLAN

        # If a plan was shown but not yet approved, handle the user's response first
        if is_plan_mode and self._awaiting_plan_approval():
            result = self._handle_plan_approval(user_input)
            if result is not None:
                return result
            # None means "approved — fall through and execute"

        # Check session limit before processing
        self._check_and_handle_session_limit()

        user_message = Message(role="user", content=user_input, images=images or None)
        self._save_message(user_message)

        # Reset loop detector for this user request
        self.loop_detector.reset()

        iteration = 0
        # A plan is "pending" on the first pass when in plan mode and no plan exists yet
        needs_plan = is_plan_mode and self.mode_manager.current_plan is None

        while iteration < max_iterations:
            # Compact history if approaching context token budget
            compacted_history, was_compacted = self.context_manager.compact_history(self.history)
            if was_compacted:
                self.history = compacted_history

            planned_messages = self.planner.plan(self.history)

            # Inject advisory if approaching maximum iterations
            advisory = self.loop_detector.get_turn_advisory(iteration, max_iterations)
            if advisory:
                planned_messages.append(Message(role="system", content=advisory))

            # Inject previous-session context after the system message (first iteration only)
            if self._context_summary and iteration == 0:
                for i, msg in enumerate(planned_messages):
                    if msg.role == "system":
                        planned_messages.insert(
                            i + 1,
                            Message(
                                role="system",
                                content=f"\n\n[Previous conversation context]\n{self._context_summary}",
                            ),
                        )
                        break

            # Planning phase: inject plan prompt and withhold tools so LLM writes the plan first
            if needs_plan and iteration == 0:
                for i, msg in enumerate(planned_messages):
                    if msg.role == "system":
                        planned_messages.insert(
                            i + 1, Message(role="system", content=f"\n\n{PLAN_MODE_PROMPT}")
                        )
                        break
                tools_for_call = None
                status_msg = "[bold yellow]DevOrch is planning..."
            else:
                tools_for_call = [tool.schema() for tool in self.tools]
                status_msg = "[bold blue]DevOrch is thinking..."

            send_messages = prune_old_images(planned_messages, keep=self.keep_recent_images)
            response = self._call_model(send_messages, tools_for_call, status_msg)

            # Record token usage
            usage = getattr(response, "usage", None) or extract_token_usage(
                getattr(response, "raw", None)
            )
            self.context_manager.record_usage(usage)
            self.last_turn_usage = usage
            self.last_turn_cost = self.costs.add(self.provider.name, self.provider.model, usage)

            # Persist tool_calls metadata for providers that need it (e.g. Mistral)
            if response.tool_calls:
                response.message.metadata = response.message.metadata or {}
                response.message.metadata["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in response.tool_calls
                ]

            self._save_message(response.message)

            # Plan just created — register it in ModeManager and wait for approval
            if needs_plan and not response.tool_calls:
                self.mode_manager.start_plan(user_input)
                self._check_and_handle_session_limit()
                return response.message.content

            # Final answer — no tool calls
            if not response.tool_calls:
                self._check_and_handle_session_limit()
                return response.message.content

            for call in response.tool_calls:
                self._display_tool_call(call)

                # Loop safeguard check before execution
                verdict = self.loop_detector.check_and_record(call.name, call.arguments)
                if verdict.should_block:
                    console.print(f"    [bold red]⛔ Safeguard: {verdict.message}[/bold red]")
                    tool_output = (
                        f"Error: Action blocked by DevOrch safeguard to prevent infinite loop. "
                        f"{verdict.message}"
                    )
                else:
                    tool_output = self.executor.execute(call.name, call.arguments)
                    # Record result in loop detector to track errors and oscillations
                    post_verdict = self.loop_detector.check_and_record(
                        call.name, call.arguments, result=tool_output
                    )
                    if post_verdict.message and post_verdict.severity != LoopSeverity.NONE:
                        notice_text = post_verdict.message
                        if not notice_text.startswith("DevOrch Safeguard Notice:"):
                            notice_text = f"DevOrch Safeguard Notice: {notice_text}"
                        tool_output = f"{tool_output}\n\n[{notice_text}]"

                self._display_tool_result(
                    call.name, tool_output, getattr(self.executor, "last_run_seconds", None)
                )
                self._save_message(
                    Message(
                        role="tool",
                        content=str(tool_output),
                        name=call.name,
                        tool_call_id=call.id,
                    )
                )

            iteration += 1

        return (
            f"Reached maximum turn limit ({max_iterations} iterations). "
            "Please review progress so far or provide additional instructions."
        )
