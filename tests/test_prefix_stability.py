"""Guards for prompt-cache friendliness.

Automatic provider caches (OpenAI, DeepSeek, Kimi, Gemini...) and explicit ones (Anthropic,
OpenRouter) only hit when the start of the request is byte-identical between calls. These tests
fail if something volatile (timestamps, counters, random ids) leaks into the system prompt.
"""

import json

from cli.commands._shared import SimplePlanner
from schemas.message import Message
from tools.filesystem import FilesystemTool
from tools.shell import ShellTool


def _planner():
    return SimplePlanner(
        memory_context="MEM",
        project_context="PROJECT RULES",
        project_memory_context="PROJECT MEMORY",
        tools=[ShellTool(), FilesystemTool()],
    )


def test_system_prompt_identical_across_calls():
    p = _planner()
    first = p.plan([Message(role="user", content="a")])[0].content
    second = p.plan([Message(role="user", content="a"), Message(role="assistant", content="b")])[
        0
    ].content
    assert first == second


def test_system_prompt_identical_across_planner_instances():
    assert _planner().plan([])[0].content == _planner().plan([])[0].content


def test_history_is_appended_unmodified_after_system_prompt():
    history = [Message(role="user", content="hi"), Message(role="assistant", content="yo")]
    planned = _planner().plan(history)
    assert planned[0].role == "system" and planned[1:] == history


def test_tool_schemas_are_deterministic():
    a = json.dumps([t.schema() for t in [ShellTool(), FilesystemTool()]], sort_keys=False)
    b = json.dumps([t.schema() for t in [ShellTool(), FilesystemTool()]], sort_keys=False)
    assert a == b


def test_system_prompt_has_no_volatile_markers():
    import re

    text = _planner().plan([])[0].content
    assert not re.search(r"\b20\d\d-\d\d-\d\d\b", text), "date in system prompt breaks caching"
    assert not re.search(r"\b\d{2}:\d{2}:\d{2}\b", text), "time in system prompt breaks caching"
