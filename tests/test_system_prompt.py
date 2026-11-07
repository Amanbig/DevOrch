"""Guards for the system prompt.

A prompt cannot be unit-tested for quality, but it can be checked for the specific mistakes found in real
sessions: contradictions between the prompt and tool descriptions, rules that push the model to act on
questions, references to tools that do not exist, and bloat.
"""

import re

from devorch.cli.commands._shared import SYSTEM_PROMPT, SimplePlanner
from devorch.core.memory import MemoryTool
from devorch.tools.agent import SUB_AGENT_SYSTEM_PROMPT, AgentTool
from devorch.tools.edit import EditTool
from devorch.tools.filesystem import FilesystemTool
from devorch.tools.git import GitTool
from devorch.tools.grep import GrepTool
from devorch.tools.search import SearchTool
from devorch.tools.shell import ShellTool
from devorch.tools.task import TaskTool
from devorch.tools.terminal_session import TerminalSessionTool
from devorch.tools.websearch import WebFetchTool, WebSearchTool

TOOLS = [
    ShellTool,
    TerminalSessionTool,
    FilesystemTool,
    SearchTool,
    GrepTool,
    EditTool,
    GitTool,
    TaskTool,
    WebSearchTool,
    WebFetchTool,
    MemoryTool,
    AgentTool,
]
TOOL_NAMES = {t.name for t in TOOLS}
LOWER = SYSTEM_PROMPT.lower()


def test_the_prompt_stays_small():
    # it was ~6,100 chars (~1,500 tokens), 61% of it repeating tool descriptions the API already sends
    assert len(SYSTEM_PROMPT) <= 4200


def test_the_old_contradictory_rules_are_gone():
    banned = [
        "prefer action over explanation",  # made the model edit files when only asked a question
        "do not just give instructions",
        "do not ask the user to run commands manually",  # it installed things without asking
        "primary tool for all terminal",  # it opened a GUI terminal just to run pytest
        "for all terminal needs",
        "must use them",
    ]
    for phrase in banned:
        assert phrase not in LOWER, phrase


def test_questions_are_answered_not_acted_on():
    assert "question" in LOWER
    assert "do not edit files" in LOWER
    assert "ask before making it" in LOWER
    assert (
        "what could we improve" in LOWER
    )  # the exact kind of question that triggered unwanted edits


def test_environment_changes_need_asking_first():
    assert "ask first" in LOWER
    for risky in ("installing packages", "virtual environments", "deleting files"):
        assert risky in LOWER, risky


def test_it_tells_the_model_to_verify_instead_of_guessing():
    assert "never guess" in LOWER
    assert "report the real outcome" in LOWER
    assert "do not say something works unless you saw it work" in LOWER


def test_it_breaks_retry_loops():
    assert "do not repeat the same call" in LOWER
    assert "after two failed attempts" in LOWER


def test_shell_and_terminal_session_have_distinct_jobs():
    assert re.search(r"`shell`: any command that finishes", SYSTEM_PROMPT)
    assert re.search(r"`terminal_session`: only long-running or interactive", SYSTEM_PROMPT)
    assert "`gui=true`) only if the user asks" in SYSTEM_PROMPT


def test_the_terminal_tool_description_no_longer_claims_to_be_primary():
    description = TerminalSessionTool.description.lower()
    assert "primary tool" not in description
    assert "`shell` tool for commands that finish" in description


def test_the_prompt_asks_for_short_reports():
    assert "concise" in LOWER and "what you changed" in LOWER


def _tool_section() -> str:
    start = SYSTEM_PROMPT.index("## Choose the right tool")
    return SYSTEM_PROMPT[start : SYSTEM_PROMPT.index("## Reply")]


def test_every_tool_the_prompt_mentions_exists():
    mentioned = set()
    for line in _tool_section().splitlines():
        if line.startswith("- `"):
            head = line.split(":", 1)[0]
            mentioned |= set(re.findall(r"`([a-z_]+)`", head))
    assert mentioned, "no tool bullets found"
    assert mentioned <= TOOL_NAMES, mentioned - TOOL_NAMES


def test_every_tool_has_guidance():
    section = _tool_section()
    for name in TOOL_NAMES:
        assert f"`{name}`" in section, f"the prompt never says when to use `{name}`"


def test_sections_are_in_a_sensible_order_and_not_numbered_oddly():
    headings = re.findall(r"^## (.+)$", SYSTEM_PROMPT, re.MULTILINE)
    assert headings == [
        "Decide what the user is asking",
        "Work carefully",
        "Choose the right tool",
        "Reply",
    ]
    assert not re.search(r"^\d+\. \*\*", SYSTEM_PROMPT, re.MULTILINE)  # the old list skipped "3."


def test_the_planner_sends_the_prompt_verbatim_first():
    planned = SimplePlanner(tools=[ShellTool()]).plan([])
    assert planned[0].role == "system" and planned[0].content.startswith(SYSTEM_PROMPT)


def test_the_sub_agent_does_not_modify_files_unprompted():
    text = SUB_AGENT_SYSTEM_PROMPT.lower()
    assert "do not modify files" in text and "never guess" in text
