"""
Shared utilities for DevOrch CLI commands.

Exports: console, SYSTEM_PROMPT, SimplePlanner, create_provider, build_tools, resolve_mode
"""

import os
import platform

import typer

from devorch.config.project_settings import load_project_settings
from devorch.config.settings import Settings
from devorch.core.agent import Agent
from devorch.core.executor import ToolExecutor
from devorch.core.mcp import MCPManager
from devorch.core.memory import MemoryTool
from devorch.core.modes import AgentMode, ModeManager
from devorch.core.planner import Planner
from devorch.core.pricing import CostTracker, PriceBook, parse_overrides
from devorch.providers import PROVIDERS, get_provider
from devorch.schemas.message import Message
from devorch.tools.agent import AgentTool
from devorch.tools.edit import EditTool
from devorch.tools.filesystem import FilesystemTool
from devorch.tools.git import GitTool
from devorch.tools.grep import GrepTool
from devorch.tools.search import SearchTool
from devorch.tools.shell import ShellTool
from devorch.tools.task import TaskTool
from devorch.tools.terminal_session import TerminalSessionTool
from devorch.tools.websearch import WebFetchTool, WebSearchTool
from devorch.utils.logger import get_console, print_error, print_success, print_warning

console = get_console()

SYSTEM_PROMPT = """You are DevOrch, an AI coding assistant that works in the user's terminal, on their machine and in their project. You have real tools to read and change files and to run commands: use them, and never say you cannot access files or run commands.

## Decide what the user is asking
- A QUESTION, explanation, review or opinion ("what does X do?", "why is this failing?", "what could we improve?", "what do you think?"): investigate with read-only tools and ANSWER. Do not edit files, install anything, or run commands that change state. If a change looks worthwhile, describe it and ask before making it.
- A REQUEST to change or do something ("fix", "add", "create", "refactor", "run", "install"): do it with the tools instead of telling the user how. Run commands yourself.
- Unclear, large or risky: ask one short question, or state a two-line plan first.

## Work carefully
- Look before you answer or edit. Use `search` or `grep` to find things, then read only the lines you need. Never guess file contents, paths or command output; if you don't know, find out or say so.
- Ask first before anything hard to undo or that changes the environment: installing packages, creating virtual environments, editing global or system config, deleting files, force operations. Check what already exists (an existing `.venv`, `pyproject.toml`, `package.json`) and use it. If a tool is missing, say what you would run to install it and ask.
- Make the smallest change that solves the problem. Match the project's style. Leave unrelated code alone.
- After changing code, run the project's tests or linter when there are any, and report the real outcome, including failures. Do not say something works unless you saw it work.
- If a call fails or finds nothing, check the path or name, widen the search, or try another approach. Do not repeat the same call. After two failed attempts, say what you tried and ask.

## Choose the right tool
- `shell`: any command that finishes: tests, builds, installs, formatters. Use the `git` tool for git.
- `terminal_session`: only long-running or interactive processes (dev servers, watchers, REPLs). Open a visible window (`gui=true`) only if the user asks to see a terminal. If a session is running and the user asks about it, read it with `terminal_session read` instead of saying you cannot see it.
- `filesystem`, `search`, `grep`, `edit`: read, find and change files. Do not use `cat`, `ls`, `find` or `sed` in the shell. `search` patterns are relative to the directory searched. Change existing files with `edit` (small replacements); write whole files only when creating them.
- `task`: only for work with 3 or more steps. Keep one task in progress and mark each done as you finish it.
- `websearch`, `webfetch`: for current information or a URL the user gave, not for things you can read in the project.
- `agent`: hand off a self-contained sub-task that needs its own context (for example "review auth.py"). Not for a single tool call.
- `memory`: save only lasting, non-obvious facts: user preferences, corrections, project decisions. Never secrets or one-off details.

## Reply
- Be concise and plain. Lead with the answer or the result.
- After doing work, say what you changed (file paths), what you ran and what happened, and anything the user has to decide.
- Do not paste whole files or long tool output back; quote only the relevant lines.
- Follow the project instructions (DEVORCH.md, CLAUDE.md, AGENTS.md) if they appear below."""


class SimplePlanner(Planner):
    def __init__(
        self,
        memory_context: str = "",
        project_context: str = "",
        project_memory_context: str = "",
        tools: list | None = None,
    ):
        self.memory_context = memory_context
        self.project_context = project_context
        self.project_memory_context = project_memory_context
        self._tools = tools or []

    def update_tools(self, tools: list) -> None:
        """Refresh the tool list — call this after adding/removing MCP servers."""
        self._tools = tools

    def plan(self, history: list[Message]) -> list[Message]:
        prompt = SYSTEM_PROMPT

        # Append runtime environment & host OS shell guidance
        os_name = platform.system()
        os_release = platform.release()
        os_machine = platform.machine()
        cwd = os.getcwd()

        if os_name == "Windows":
            shell_info = (
                f"\n\nENVIRONMENT & SYSTEM CONTEXT:\n"
                f"- Host OS: Windows ({os_release}, {os_machine})\n"
                f"- Current Working Directory: {cwd}\n"
                f"- Shell: Windows cmd.exe / PowerShell\n"
                f"- IMPORTANT SHELL RULES FOR WINDOWS:\n"
                f"  * Do NOT use Unix shell commands like `pwd`, `ls`, `ls -la`, `cat`, `touch`, `rm -rf`, `grep`, or `export`.\n"
                f"  * To inspect directory contents: use the `filesystem` tool with `action='list'`, `path='.'`.\n"
                f"  * To read files: use the `filesystem` tool with `action='read'`.\n"
                f"  * To search files: use `search` (glob) or `grep` (content search).\n"
                f"  * For builds & CLI tools, use direct commands: `pip`, `uv`, `npm`, `git`, `python`, `pytest`.\n"
                f"  * For Windows file paths in shell commands, use backslashes `\\` or wrap paths in quotes."
            )
        else:
            shell_info = (
                f"\n\nENVIRONMENT & SYSTEM CONTEXT:\n"
                f"- Host OS: {os_name} ({os_release}, {os_machine})\n"
                f"- Current Working Directory: {cwd}\n"
                f"- Shell: bash/sh\n"
                f"- Prefer using `filesystem` tool for reading and listing files to minimize token usage."
            )
        prompt += shell_info

        # Append project rules/guidelines (from DEVORCH.md or CLAUDE.md)
        if self.project_context:
            prompt += "\n\n" + self.project_context

        # Append persistent per-project memory (cross-session decisions & learnings)
        if self.project_memory_context:
            prompt += "\n\n" + self.project_memory_context

        # Append a live tool summary so the LLM knows exactly what's loaded,
        # including any MCP tools added after startup.
        if self._tools:
            builtin = [t.name for t in self._tools if not t.name.startswith("mcp_")]
            mcp = [t.name for t in self._tools if t.name.startswith("mcp_")]
            tool_section = f"\n\nLoaded tools: {', '.join(builtin)}"
            if mcp:
                tool_section += f"\nLoaded MCP tools: {', '.join(mcp)}"
            prompt += tool_section

        if self.memory_context:
            prompt += "\n" + self.memory_context

        return [Message(role="system", content=prompt)] + history


def create_provider(provider_name: str, model: str, settings: Settings):
    """Create and validate a provider instance."""
    provider_name = provider_name.lower()

    if provider_name not in PROVIDERS:
        print_error(f"Unknown provider '{provider_name}'. Available: {', '.join(PROVIDERS.keys())}")
        raise typer.Exit(1)

    api_key = settings.get_api_key(provider_name)

    if provider_name != "local" and not api_key:
        env_var_name = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GOOGLE_API_KEY",
        }.get(provider_name, f"{provider_name.upper()}_API_KEY")

        print_error(f"No API key found for {provider_name}.")
        print_error(
            f"Use 'devorch set-key {provider_name}' or set {env_var_name} environment variable"
        )
        raise typer.Exit(1)

    if not model:
        model = settings.get_default_model(provider_name)

    kwargs = {}
    if provider_name == "local":
        base_url = settings.get_base_url(provider_name)
        if base_url:
            kwargs["base_url"] = base_url

    return get_provider(provider_name, model=model, api_key=api_key, **kwargs)


def build_tools(
    settings: Settings,
    *,
    include_terminal: bool = True,
    no_mcp: bool = False,
    mcp_only: list[str] | None = None,
) -> list:
    """Build the standard tool list and extend with any configured MCP tools.

    Args:
        include_terminal: Include TerminalSessionTool (False for edit command).
        no_mcp: Skip all MCP servers entirely.
        mcp_only: If given, only connect servers whose names are in this list.
    """
    tools = [
        ShellTool(),
        GitTool(),
        FilesystemTool(),
        SearchTool(),
        GrepTool(),
        EditTool(),
        TaskTool(),
        WebSearchTool(),
        WebFetchTool(),
        MemoryTool(),
    ]
    if include_terminal:
        tools.insert(1, TerminalSessionTool())

    if no_mcp:
        return tools

    mcp_config = settings.mcp_servers or {}
    if mcp_only:
        unknown = [n for n in mcp_only if n not in mcp_config]
        if unknown:
            print_error(
                f"Unknown MCP server(s): {', '.join(unknown)}. "
                f"Configured: {', '.join(mcp_config) or 'none'}"
            )
            raise typer.Exit(1)
        mcp_config = {k: v for k, v in mcp_config.items() if k in mcp_only}

    if mcp_config:
        mcp_manager = MCPManager()
        with console.status("[bold cyan]Connecting MCP servers...", spinner="dots"):
            started = mcp_manager.load_from_config(mcp_config)
        if started:
            print_success(f"MCP servers connected: {', '.join(started)}")
            tools.extend(mcp_manager.get_all_tools())

    return tools


def load_project_mode() -> str | None:
    """Mode requested by .devorch/settings.yaml (untrusted ``auto`` is downgraded to ``ask``)."""
    ps = load_project_settings()
    return ps.effective_mode() if ps else None


def print_project_notices(settings) -> None:
    for notice in getattr(settings, "project_notices", []):
        print_warning(notice)


SKIP_PERMISSIONS_HELP = (
    "Skip every permission prompt (same as --mode auto). Built-in dangerous-command blocks and "
    "your deny rules still apply."
)


def resolve_mode(
    mode_str: str | None,
    default: AgentMode = AgentMode.AUTO,
    skip_permissions: bool = False,
) -> AgentMode:
    """Parse and validate a mode string, exit with error on bad input.

    ``skip_permissions`` (``--dangerously-skip-permissions``) forces AUTO, which never prompts; deny
    rules and the built-in dangerous-command blocks are still enforced by the executor.
    """
    if skip_permissions:
        if mode_str and mode_str.lower() != "auto":
            print_error(f"--dangerously-skip-permissions conflicts with --mode {mode_str}")
            raise typer.Exit(1)
        return AgentMode.AUTO
    if not mode_str:
        project_mode = load_project_mode()
        return AgentMode(project_mode) if project_mode else default
    try:
        return AgentMode(mode_str.lower())
    except ValueError as err:
        print_error(f"Unknown mode '{mode_str}'. Choose from: ask, auto, plan")
        raise typer.Exit(1) from err


def build_agent(
    llm,
    tools: list,
    memory_ctx: str,
    agent_mode: AgentMode,
    project_ctx: str = "",
    project_memory_ctx: str = "",
    pricing: dict | None = None,
    context_windows: dict | None = None,
) -> "Agent":
    """Construct a configured Agent ready to run.

    AgentTool is injected after construction since it needs the provider reference.
    The planner is stored on agent.planner — call agent.planner.update_tools(tools)
    after adding/removing MCP servers mid-session.
    """
    mode_manager = ModeManager(default_mode=agent_mode)
    executor = ToolExecutor(tools=tools, mode_manager=mode_manager)
    planner = SimplePlanner(
        memory_context=memory_ctx,
        project_context=project_ctx,
        project_memory_context=project_memory_ctx,
        tools=tools,
    )

    agent = Agent(
        provider=llm,
        planner=planner,
        executor=executor,
        tools=tools,
        mode_manager=mode_manager,
    )

    # Inject AgentTool now that we have both the provider and the full tool list
    agent.costs = CostTracker(PriceBook(parse_overrides(pricing)))
    agent.set_context_overrides(context_windows)
    agent_tool = AgentTool(provider=llm, tools=tools, costs=agent.costs)
    executor.tools[agent_tool.name] = agent_tool
    agent.tools.append(agent_tool)
    planner.update_tools(agent.tools)

    return agent
