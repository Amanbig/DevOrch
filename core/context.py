"""Context and token management for DevOrch.

Handles token counting/estimation, history compaction, tool output pruning,
and session-wide token usage tracking.
"""

import json
from dataclasses import dataclass, field

from schemas.message import Message, TokenUsage


def estimate_tokens(text: str) -> int:
    """Heuristic token estimation (~3.8 - 4 characters per token).

    Accurate enough across models without requiring heavy binary dependencies.
    """
    if not text:
        return 0
    # Words + punctuation heuristic
    char_count = len(text)
    words = len(text.split())
    # Blend character count (div 4) and word count (times 1.3)
    estimated = int((char_count / 4.0 + words * 1.3) / 2.0)
    return max(1, estimated)


def count_message_tokens(message: Message) -> int:
    """Estimate token count of a single message including metadata."""
    tokens = 4  # message envelope framing overhead (role, markers)
    if message.content:
        tokens += estimate_tokens(message.content)
    if message.name:
        tokens += estimate_tokens(message.name)
    if message.tool_call_id:
        tokens += estimate_tokens(message.tool_call_id)
    if message.metadata and "tool_calls" in message.metadata:
        try:
            tc_json = json.dumps(message.metadata["tool_calls"])
            tokens += estimate_tokens(tc_json)
        except Exception:
            pass
    return tokens


def count_history_tokens(messages: list[Message]) -> int:
    """Estimate total tokens in a list of messages."""
    return sum(count_message_tokens(m) for m in messages) + 3  # primer tokens


def compact_tool_output(content: str, max_lines: int = 40, max_chars: int = 2500) -> str:
    """Intelligently compact a long tool output to conserve tokens.

    Preserves the head and tail lines with a clear truncation note.
    """
    if not content or (len(content) <= max_chars and content.count("\n") <= max_lines):
        return content

    lines = content.splitlines()
    total_lines = len(lines)

    if total_lines <= max_lines and len(content) <= max_chars:
        return content

    head_count = max(5, max_lines // 2)
    tail_count = max(5, max_lines // 3)

    if total_lines > (head_count + tail_count):
        head_lines = lines[:head_count]
        tail_lines = lines[-tail_count:]
        omitted = total_lines - head_count - tail_count
        separator = f"\n[... {omitted} lines omitted to conserve tokens ...]\n"
        compacted = "\n".join(head_lines) + separator + "\n".join(tail_lines)
    else:
        # Long lines without newlines
        head_chars = max_chars // 2
        tail_chars = max_chars // 3
        omitted_chars = len(content) - head_chars - tail_chars
        separator = f"\n[... {omitted_chars} chars omitted to conserve tokens ...]\n"
        compacted = content[:head_chars] + separator + content[-tail_chars:]

    return compacted


@dataclass
class SessionTokenStats:
    """Cumulative token statistics for a session."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    total_turns: int = 0
    history_compactions: int = 0
    turn_usages: list[TokenUsage] = field(default_factory=list)

    def add_turn(self, usage: TokenUsage | None):
        """Record usage from a turn."""
        self.total_turns += 1
        if usage:
            self.turn_usages.append(usage)
            self.prompt_tokens += usage.prompt_tokens
            self.completion_tokens += usage.completion_tokens
            self.total_tokens += usage.total_tokens
            self.cached_tokens += usage.cached_tokens
        else:
            self.turn_usages.append(TokenUsage())

    @property
    def last_turn(self) -> TokenUsage | None:
        return self.turn_usages[-1] if self.turn_usages else None


class ContextManager:
    """Manages context budget, message compaction, and token usage."""

    def __init__(
        self,
        max_context_tokens: int = 24000,
        compact_threshold_tokens: int = 16000,
        preserve_recent_turns: int = 4,
    ):
        self.max_context_tokens = max_context_tokens
        self.compact_threshold_tokens = compact_threshold_tokens
        self.preserve_recent_turns = preserve_recent_turns
        self.stats = SessionTokenStats()

    def record_usage(self, usage: TokenUsage | None):
        """Record turn usage in stats."""
        self.stats.add_turn(usage)

    def should_compact(self, messages: list[Message]) -> bool:
        """Check if message history exceeds compaction threshold."""
        return count_history_tokens(messages) > self.compact_threshold_tokens

    def compact_history(
        self,
        messages: list[Message],
        force: bool = False,
    ) -> tuple[list[Message], bool]:
        """Compact conversation history to fit comfortably within token budget.

        Rules:
        1. Always preserve system messages (rules, instructions).
        2. Always preserve the very first user message (original user goal).
        3. Always preserve the last N messages (immediate working context).
        4. Compact older tool messages (prune huge file reads, logs).
        5. Never break tool call / tool response pairings.

        Returns:
            (compacted_messages, was_compacted)
        """
        current_tokens = count_history_tokens(messages)
        if not force and current_tokens <= self.compact_threshold_tokens:
            return messages, False

        if len(messages) <= self.preserve_recent_turns + 2:
            # Too short to safely compact structure, compact individual tool contents
            compacted_msgs = []
            modified = False
            for msg in messages:
                if msg.role == "tool":
                    compacted_content = compact_tool_output(
                        msg.content, max_lines=25, max_chars=1200
                    )
                    if len(compacted_content) < len(msg.content):
                        modified = True
                    compacted_msgs.append(
                        Message(
                            role=msg.role,
                            content=compacted_content,
                            name=msg.name,
                            tool_call_id=msg.tool_call_id,
                            metadata=msg.metadata,
                        )
                    )
                else:
                    compacted_msgs.append(msg)
            if modified:
                self.stats.history_compactions += 1
            return compacted_msgs, modified

        # Identify boundary for older messages vs recent messages
        recent_cutoff = max(len(messages) - self.preserve_recent_turns, 2)
        compacted: list[Message] = []
        modified = False

        for i, msg in enumerate(messages):
            if msg.role == "system" or i == 0:
                # Always keep system messages and initial user request intact
                compacted.append(msg)
                continue

            if i >= recent_cutoff:
                # Recent turns: keep full fidelity
                compacted.append(msg)
                continue

            # Older turns: compact tool results
            if msg.role == "tool":
                trimmed = compact_tool_output(msg.content, max_lines=25, max_chars=1200)
                if len(trimmed) < len(msg.content):
                    modified = True
                compacted.append(
                    Message(
                        role="tool",
                        content=trimmed,
                        name=msg.name,
                        tool_call_id=msg.tool_call_id,
                        metadata=msg.metadata,
                    )
                )
            elif msg.role == "assistant" and len(msg.content) > 2000:
                # Compact overly verbose older thoughts if present
                trimmed = compact_tool_output(msg.content, max_lines=30, max_chars=1500)
                if len(trimmed) < len(msg.content):
                    modified = True
                compacted.append(
                    Message(
                        role="assistant",
                        content=trimmed,
                        name=msg.name,
                        tool_call_id=msg.tool_call_id,
                        metadata=msg.metadata,
                    )
                )
            else:
                compacted.append(msg)

        if modified:
            self.stats.history_compactions += 1

        return compacted, modified
