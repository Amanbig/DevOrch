from core.context import (
    ContextManager,
    compact_tool_output,
    count_message_tokens,
    estimate_tokens,
)
from schemas.message import Message, TokenUsage


class TestContextManager:
    def test_estimate_tokens(self):
        assert estimate_tokens("") == 0
        text = "Hello world! This is a test sentence for estimating token counts."
        tokens = estimate_tokens(text)
        assert tokens > 0
        assert tokens < len(text)

    def test_count_message_tokens(self):
        msg = Message(role="user", content="How do I optimize my code?")
        tokens = count_message_tokens(msg)
        assert tokens > 5

    def test_compact_tool_output_short(self):
        short = "Line 1\nLine 2\nLine 3"
        compacted = compact_tool_output(short, max_lines=10)
        assert compacted == short

    def test_compact_tool_output_long(self):
        lines = [f"Line {i}" for i in range(100)]
        long_text = "\n".join(lines)
        compacted = compact_tool_output(long_text, max_lines=20)
        assert len(compacted) < len(long_text)
        assert "omitted to conserve tokens" in compacted
        assert "Line 0" in compacted
        assert "Line 99" in compacted

    def test_compact_history(self):
        ctx = ContextManager(compact_threshold_tokens=50)
        messages = [
            Message(role="system", content="System instruction"),
            Message(role="user", content="Initial user prompt"),
            Message(role="assistant", content="Let me run a command"),
            Message(
                role="tool",
                content="\n".join([f"Output line {i}" for i in range(100)]),
                name="shell",
                tool_call_id="call_1",
            ),
            Message(role="assistant", content="Now let me check another thing"),
            Message(role="user", content="Follow-up question"),
        ]

        compacted, modified = ctx.compact_history(messages, force=True)
        assert modified is True
        assert len(compacted) == len(messages)
        # Verify system message and initial user prompt are intact
        assert compacted[0].content == "System instruction"
        assert compacted[1].content == "Initial user prompt"
        # Verify tool output was compacted
        assert "omitted to conserve tokens" in compacted[3].content
        # Verify pairing preserved
        assert compacted[3].tool_call_id == "call_1"

    def test_session_token_stats(self):
        ctx = ContextManager()
        ctx.record_usage(TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150))
        ctx.record_usage(TokenUsage(prompt_tokens=80, completion_tokens=40, total_tokens=120))

        assert ctx.stats.total_turns == 2
        assert ctx.stats.prompt_tokens == 180
        assert ctx.stats.completion_tokens == 90
        assert ctx.stats.total_tokens == 270
