"""Agent loop detection and execution safeguards for DevOrch.

Detects duplicate tool calls, error thrashing, oscillation loops, and turn-limit
approaches to prevent wasted tokens and infinite agent loops.
"""

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class LoopSeverity(Enum):
    NONE = "none"
    WARNING = "warning"
    HALT = "halt"


@dataclass
class LoopVerdict:
    severity: LoopSeverity = LoopSeverity.NONE
    message: str | None = None
    should_block: bool = False


@dataclass
class ToolExecutionRecord:
    tool_name: str
    args_hash: str
    args_summary: str
    is_error: bool
    result_preview: str


def is_error_result(result: Any) -> bool:
    """Whether a tool result reports a failure.

    Looks at the *start* of the result: tools report failure by beginning with "Error ..." (and the
    shell tool returns just STDERR when a command prints nothing else). A result that merely
    contains the word, such as a source file mentioning "error:", is not a failure.
    """
    if result is None:
        return False
    first = str(result).lstrip().split("\n", 1)[0].lower()
    return first.startswith(
        ("error", "stderr:", "failed", "filesystem error", "search error", "memory error")
    )


class LoopDetector:
    """Monitors agent tool invocations to detect and prevent degenerative loops.

    Use it around each tool call as: ``check_and_record(name, args)`` *before* running the tool
    (records the call; detects duplicates and oscillation; may halt), then
    ``record_result(name, args, output)`` *after* (updates that same call with its outcome and detects
    error thrashing). Passing ``result=`` to ``check_and_record`` records a finished call in one step.
    """

    def __init__(
        self,
        duplicate_warning_threshold: int = 2,
        duplicate_halt_threshold: int = 3,
        error_threshold: int = 3,
    ):
        self.duplicate_warning_threshold = duplicate_warning_threshold
        self.duplicate_halt_threshold = duplicate_halt_threshold
        self.error_threshold = error_threshold

        self.history: list[ToolExecutionRecord] = []
        self.consecutive_errors: int = 0
        self.duplicate_counter: dict[str, int] = {}

    def _hash_args(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Create a deterministic hash for a tool call."""
        try:
            serialized = json.dumps(arguments, sort_keys=True, default=str)
        except Exception:
            serialized = str(sorted(arguments.items()))
        combined = f"{tool_name}:{serialized}"
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]

    def _summarize_args(self, arguments: dict[str, Any]) -> str:
        """Create a compact string representation of arguments for diagnostics."""
        items = []
        for k, v in sorted(arguments.items()):
            v_str = str(v)
            if len(v_str) > 40:
                v_str = v_str[:37] + "..."
            items.append(f"{k}={v_str}")
        return ", ".join(items)

    def check_and_record(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any = None,
    ) -> LoopVerdict:
        """Record tool call and verify if it constitutes a loop or thrashing."""
        call_hash = self._hash_args(tool_name, arguments)
        args_summary = self._summarize_args(arguments)

        # Check consecutive duplicates
        consecutive_duplicates = 0
        for record in reversed(self.history):
            if record.args_hash == call_hash:
                consecutive_duplicates += 1
            else:
                break

        # Error status only changes when we actually know the outcome. A call recorded *before* it
        # runs has no result yet and must not reset the error streak.
        is_error = is_error_result(result)
        if result is not None:
            self.consecutive_errors = self.consecutive_errors + 1 if is_error else 0
        result_str = str(result) if result is not None else ""

        # Create record
        record = ToolExecutionRecord(
            tool_name=tool_name,
            args_hash=call_hash,
            args_summary=args_summary,
            is_error=is_error,
            result_preview=result_str[:120],
        )
        self.history.append(record)

        # 1. Check exact duplicate halt threshold
        if consecutive_duplicates >= self.duplicate_halt_threshold - 1:
            return LoopVerdict(
                severity=LoopSeverity.HALT,
                should_block=True,
                message=(
                    f"DevOrch Safeguard: Tool '{tool_name}' called {consecutive_duplicates + 1} times "
                    f"with identical arguments ({args_summary}). Execution halted to prevent an infinite loop. "
                    "Please synthesize your answer or choose a different approach."
                ),
            )

        # 2. Check exact duplicate warning threshold
        if consecutive_duplicates >= self.duplicate_warning_threshold - 1:
            return LoopVerdict(
                severity=LoopSeverity.WARNING,
                should_block=False,
                message=(
                    f"DevOrch Safeguard Notice: You have already executed '{tool_name}' with these exact arguments "
                    f"({args_summary}). If this did not yield the needed result, switch strategies or use a different tool."
                ),
            )

        # 3. Check consecutive error thrashing
        if self.consecutive_errors >= self.error_threshold:
            return LoopVerdict(
                severity=LoopSeverity.WARNING,
                should_block=False,
                message=(
                    f"DevOrch Safeguard Notice: Last {self.consecutive_errors} tool calls resulted in errors. "
                    "Please carefully review the error messages, check file paths, and reconsider the approach."
                ),
            )

        # 4. Check ping-pong oscillation (A, B, A, B)
        if len(self.history) >= 4:
            h = self.history
            if (
                h[-1].args_hash == h[-3].args_hash
                and h[-2].args_hash == h[-4].args_hash
                and h[-1].args_hash != h[-2].args_hash
            ):
                return LoopVerdict(
                    severity=LoopSeverity.WARNING,
                    should_block=False,
                    message=(
                        f"DevOrch Safeguard Notice: Detected oscillating loop between '{h[-1].tool_name}' "
                        f"and '{h[-2].tool_name}'. Stop repeating this pattern and provide your best answer."
                    ),
                )

        return LoopVerdict(severity=LoopSeverity.NONE)

    def record_result(self, tool_name: str, arguments: dict[str, Any], result: Any) -> LoopVerdict:
        """Attach a finished tool call's outcome to the record made by ``check_and_record``.

        Does not add a record, so the call is not counted twice. Returns a warning when the last few
        calls all failed.
        """
        call_hash = self._hash_args(tool_name, arguments)
        is_error = is_error_result(result)
        for record in reversed(self.history):
            if record.args_hash == call_hash:
                record.is_error = is_error
                record.result_preview = str(result)[:120]
                break
        self.consecutive_errors = self.consecutive_errors + 1 if is_error else 0
        if self.consecutive_errors >= self.error_threshold:
            return LoopVerdict(
                severity=LoopSeverity.WARNING,
                should_block=False,
                message=(
                    f"DevOrch Safeguard Notice: Last {self.consecutive_errors} tool calls resulted in errors. "
                    "Please carefully review the error messages, check file paths, and reconsider the approach."
                ),
            )
        return LoopVerdict()

    def get_turn_advisory(self, iteration: int, max_iterations: int) -> str | None:
        """Provide a proactive nudge when approaching maximum iterations."""
        remaining = max_iterations - iteration
        if remaining == 2:
            return (
                f"[DevOrch Advisory: You have {remaining} iterations remaining before reaching the maximum turn limit. "
                "Please finalize any necessary edits and synthesize your response for the user.]"
            )
        if remaining == 1:
            return (
                "[DevOrch Advisory: This is your FINAL iteration before the turn limit. "
                "Do not make additional tool calls unless essential; provide your complete answer now.]"
            )
        return None

    def reset(self):
        """Reset the detector for a new user instruction."""
        self.history.clear()
        self.consecutive_errors = 0
        self.duplicate_counter.clear()
