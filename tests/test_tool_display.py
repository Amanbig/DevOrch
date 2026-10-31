"""Tests for tool call / result rendering."""

import io
import time

import pytest
from rich.console import Console

from core.agent import Agent
from core.executor import ToolExecutor
from schemas.message import ToolCall
from tools.base import Tool
from utils import tool_display as td

HOSTILE = [
    'echo "[/bold]"',
    "grep 'List[int]' x.py",
    "[a-z]+",
    "app/[id]/page.tsx",
    "[red]boom[/red]",
    "[/]",
    "[",
    "]]][[[",
    "[link=http://x]click[/link]",
    "x = '[/dim]'",
]


def render(*renderables) -> str:
    buf = io.StringIO()
    con = Console(file=buf, width=120, force_terminal=False, color_system=None)
    for r in renderables:
        con.print(r)
    return buf.getvalue()


@pytest.mark.parametrize("text", HOSTILE)
def test_calls_with_markup_like_text_render_verbatim(text):
    calls = [
        ("shell", {"command": text}),
        ("grep", {"pattern": text, "path": text}),
        ("search", {"pattern": text}),
        ("filesystem", {"action": "read", "path": text}),
        ("filesystem", {"action": text, "path": "x"}),
        ("edit", {"path": text}),
        ("websearch", {"query": text}),
        ("webfetch", {"url": text}),
        ("memory", {"action": "save", "name": text}),
        ("git", {"action": "diff", "ref": text}),
        ("agent", {"task": text}),
        ("custom_tool", {"x": text}),
    ]
    for name, args in calls:
        out = render(td.call_line(name, args))
        assert out.strip(), name
    assert text.split("\n")[0][:20] in render(td.call_line("shell", {"command": text}))


@pytest.mark.parametrize("text", HOSTILE)
def test_results_with_markup_like_text_render_verbatim(text):
    for name, result in [
        ("shell", f"STDOUT:\nfoo {text} bar"),
        ("shell", f"Error: {text}"),
        ("edit", f"--- a\n+++ b\n@@ -1 +1 @@\n-{text}\n+{text}"),
        ("filesystem", f"[x] Lines 1-2 of 2\n{text}"),
        ("memory", text),
        ("other", text),
    ]:
        out = render(*td.result_lines(name, result))
        assert out.strip(), (name, result)
    assert text in render(*td.result_lines("shell", f"STDOUT:\n{text}"))


def test_filesystem_path_with_brackets_is_not_eaten():
    out = render(td.call_line("filesystem", {"action": "read", "path": "app/[id]/page.tsx"}))
    assert "app/[id]/page.tsx" in out


def test_python_type_hint_in_output_is_not_eaten():
    out = render(*td.result_lines("shell", "STDOUT:\nx: List[int] = []"))
    assert "List[int]" in out


def test_task_tool_is_silent():
    assert td.call_line("task", {}) is None
    assert td.result_lines("task", "anything") == []


def test_error_only_when_result_starts_with_error():
    err = td.result_lines("shell", "Error: command denied")
    assert "✗" in render(*err)
    # a file whose *content* contains "Error:" is a normal read, not a failure
    ok = td.result_lines("filesystem", "[app.py] Lines 1-3 of 3\n1 raise ValueError\n2 # Error: x")
    assert "✓" in render(*ok) and "✗" not in render(*ok)
    # same for shell output that mentions an error
    assert "✗" not in render(*td.result_lines("shell", "STDOUT:\nTraceback...\nError: boom"))


def test_error_text_is_collapsed_and_clipped():
    (line,) = td.result_lines("shell", "Error: " + "word\n" * 200)
    assert "\n" not in line.plain and len(line.plain) <= 310 and line.plain.endswith("…")


def test_shell_output_shows_head_and_hidden_count():
    text = "STDOUT:\n" + "\n".join(f"line{i}" for i in range(30))
    out = render(*td.result_lines("shell", text))
    assert "STDOUT:" in out and "line6" in out and "line7" not in out
    assert "+23 more lines" in out


def test_short_shell_output_has_no_footer():
    out = render(*td.result_lines("shell", "STDOUT:\nhi"))
    assert "more" not in out and "hi" in out


def test_long_shell_lines_are_clipped():
    out = render(*td.result_lines("shell", "STDOUT:\n" + "x" * 1000))
    assert "…" in out and len(out) < 400


def test_multiline_command_shows_first_line_and_count():
    out = render(td.call_line("shell", {"command": "cat <<EOF\na\nb\nEOF"}))
    assert "cat <<EOF" in out and "+3 more lines" in out and "\nb" not in out


def test_diff_is_capped():
    diff = "--- a\n+++ b\n@@ -1 +1 @@\n" + "\n".join(f"+added{i}" for i in range(100))
    out = render(*td.result_lines("edit", diff))
    assert "added0" in out and "added99" not in out and "more diff lines" in out


def test_edit_without_diff_is_one_line():
    out = render(*td.result_lines("edit", "Replaced 1 occurrence in a.py"))
    assert "Replaced 1 occurrence" in out and out.count("\n") == 1


def test_duration_only_for_slow_calls():
    assert "s" not in render(*td.result_lines("grep", "a\nb", elapsed=0.2)).replace("matches", "")
    assert "2.3s" in render(*td.result_lines("grep", "a\nb", elapsed=2.3))
    assert "4.0s" in render(*td.result_lines("shell", "Error: x", elapsed=4.0))
    shell = render(*td.result_lines("shell", "STDOUT:\nhi", elapsed=5.0))
    assert "5.0s" in shell
    assert "1.5s" in render(*td.result_lines("edit", "--- a\n+++ b\n@@\n+x", elapsed=1.5))


def test_git_and_agent_lines():
    assert "git diff" in render(td.call_line("git", {"action": "diff", "ref": "main"}))
    assert "sub-agent" in render(td.call_line("agent", {"task": "review the auth module\nmore"}))
    assert "more" not in render(td.call_line("agent", {"task": "review\nmore"}))


# ── wiring ──────────────────────────────────────────────────────────────────


def _agent_with_console(monkeypatch):
    import core.agent as agent_mod

    buf = io.StringIO()
    monkeypatch.setattr(
        agent_mod, "console", Console(file=buf, width=120, force_terminal=False, color_system=None)
    )
    return Agent.__new__(Agent), buf


def test_agent_display_no_longer_crashes_on_markup(monkeypatch):
    agent, buf = _agent_with_console(monkeypatch)
    agent._display_tool_call(ToolCall("shell", {"command": 'echo "[/bold]"'}))
    agent._display_tool_result("shell", "STDOUT:\nfoo [/x] bar")
    agent._display_tool_result("edit", "--- a\n+++ b\n@@ -1 +1 @@\n-x\n+'[/red]'")
    out = buf.getvalue()
    assert "[/bold]" in out and "[/x]" in out and "[/red]" in out


class Sleepy(Tool):
    name = "sleepy"
    description = "x"

    def run(self, arguments):
        time.sleep(0.05)
        return "ok"


def test_executor_times_only_the_tool_run():
    ex = ToolExecutor([Sleepy()], require_confirmation=False)
    assert ex.execute("sleepy", {}) == "ok"
    assert 0.04 <= ex.last_run_seconds < 1.0


def test_executor_timing_resets_when_tool_does_not_run():
    ex = ToolExecutor([Sleepy()], require_confirmation=False)
    ex.execute("sleepy", {})
    ex.execute("missing", {})
    assert ex.last_run_seconds is None


def test_executor_timing_excludes_permission_prompt(monkeypatch):
    from config.permissions import PermissionChoice

    ex = ToolExecutor([Sleepy()], require_confirmation=True)

    def slow_prompt(*a, **k):
        time.sleep(0.3)  # the user taking their time to answer
        return PermissionChoice.ALLOW_ONCE

    monkeypatch.setattr(ex, "_ask_permission", slow_prompt)
    ex.execute("sleepy", {})
    assert ex.last_run_seconds < 0.25


# ── generic message helpers ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "msg", ["bad [/x] thing", "opened app/[id]/page.tsx", "x: List[int]", "[red]"]
)
def test_logger_helpers_do_not_eat_or_crash_on_brackets(monkeypatch, msg):
    from utils import logger

    buf = io.StringIO()
    monkeypatch.setattr(
        logger, "console", Console(file=buf, width=120, force_terminal=False, color_system=None)
    )
    for fn in (logger.print_error, logger.print_warning, logger.print_success, logger.print_info):
        buf.truncate(0)
        buf.seek(0)
        fn(msg)
        assert msg in buf.getvalue(), fn.__name__


def test_logger_helpers_accept_non_strings(monkeypatch):
    from utils import logger

    buf = io.StringIO()
    monkeypatch.setattr(
        logger, "console", Console(file=buf, width=120, force_terminal=False, color_system=None)
    )
    logger.print_error(ValueError("boom [/x]"))
    assert "boom [/x]" in buf.getvalue()
