"""
Shared utilities for DevOrch CLI commands.

Exports: console, SYSTEM_PROMPT, SimplePlanner, create_provider, build_tools, resolve_mode
"""

import typer

from config.settings import Settings
from core.agent import Agent
from core.executor import ToolExecutor
from core.mcp import MCPManager
from core.memory import MemoryTool
from core.modes import AgentMode, ModeManager
from core.planner import Planner
from providers import PROVIDERS, get_provider
from schemas.message import Message
from tools.edit import EditTool
from tools.filesystem import FilesystemTool
from tools.grep import GrepTool
from tools.search import SearchTool
from tools.shell import ShellTool
from tools.task import TaskTool
from tools.terminal_session import TerminalSessionTool
from tools.websearch import WebFetchTool, WebSearchTool
from utils.logger import get_console, print_error, print_success

console = get_console()

SYSTEM_PROMPT = """You are DevOrch, an AI coding assistant with access to tools for interacting with the user's computer.

IMPORTANT: You have the following tools available and MUST use them to help the user:

1. **shell** - Execute shell commands (bash/powershell). Use this to:
   - Run commands like `npm install`, `git clone`, `git status`, etc.
   - Navigate directories, create files, run scripts
   - Any short-lived terminal command that returns output

2. **terminal_session** — The PRIMARY tool for all terminal/process needs:
   - `start` — launch a command in a managed session. Defaults to 'bash' if no command.
     Set gui=true to also open a visible terminal window for the user.
   - `read`  — read recent stdout/stderr output
   - `send`  — send input to the process stdin
   - `stop`  — terminate the session
   - `list`  — show all active sessions
   - `reconnect` — reconnect to sessions from previous DevOrch runs
   Sessions persist across DevOrch restarts with unique names (e.g. 'swift-fox-a3f2').
   Use gui=true when the user wants to SEE a terminal. Use without gui for headless monitoring.

4. **filesystem** - Read/write/list files. Use this to:
   - Read file contents to understand code
   - Write or create new files
   - List directory contents

5. **search** - Find files by name patterns (like glob)

6. **grep** - Search for text patterns within files

7. **edit** - Make targeted edits to existing files

8. **task** - Track progress on multi-step work. Use this to:
   - Create a task list when working on complex requests (3+ steps)
   - Show the user what you're currently working on
   - Mark tasks complete as you finish them

   Task guidelines:
   - Use when working on multiple steps or user gives multiple items
   - Only ONE task should be 'in_progress' at a time
   - Mark tasks 'completed' immediately after finishing each one
   - content: imperative form (e.g., "Fix bug", "Run tests")
   - activeForm: present continuous (e.g., "Fixing bug", "Running tests")

9. **websearch** - Search the web for current information. Use when:
   - You need up-to-date information (news, docs, releases)
   - Looking up programming solutions or best practices
   - Finding package/library documentation
   - User asks about something you're unsure about

10. **webfetch** - Fetch content from a specific URL. Use when:
    - You need to read a documentation page
    - User provides a URL to check
    - You found a relevant URL from search results

11. **memory** - Persistent memory across conversations. Use to:
    - Save important context: user preferences, project decisions, feedback
    - Search/load memories from previous conversations
    - Memory types: user (profile), feedback (corrections), project (context), reference (links)
    - Proactively save memories when you learn something important about the user or project
    - Check memories at the start of conversations for relevant context

RULES:
- When the user asks you to CREATE something (app, file, project), USE THE TOOLS to actually do it
- Do NOT just give instructions - execute the commands yourself using the shell tool
- Do NOT ask the user to run commands manually - run them for the user
- Always prefer action over explanation — do things, don't explain how to do them
- For multi-step tasks, use the task tool to track and show progress
- Use `terminal_session` for ALL terminal needs — dev servers, scaffolds, processes, interactive shells
- If the user says "open terminal", use `terminal_session start` with gui=true so they get a visible window AND you can read output
- If the user wants you to monitor a process, use `terminal_session start` (no gui needed)
- When a GUI terminal session is active and the user asks "what did I type", "see it", "check output", or anything about the terminal, IMMEDIATELY use `terminal_session read` to read the session output — do NOT say you can't see it
- For GUI sessions: the user types in the visible window, you read output with `terminal_session read`
- For headless sessions: send commands via `send` action, read output with `read` action
- When the user corrects you or gives feedback, save it to memory for future conversations
- When you learn about the user's role, preferences, or project context, save it to memory

When executing shell commands, use the shell tool with the command to run."""


class SimplePlanner(Planner):
    def __init__(self, memory_context: str = "", tools: list | None = None):
        self.memory_context = memory_context
        self._tools = tools or []

    def update_tools(self, tools: list) -> None:
        """Refresh the tool list — call this after adding/removing MCP servers."""
        self._tools = tools

    def plan(self, history: list[Message]) -> list[Message]:
        prompt = SYSTEM_PROMPT

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


def resolve_mode(mode_str: str | None, default: AgentMode = AgentMode.AUTO) -> AgentMode:
    """Parse and validate a mode string, exit with error on bad input."""
    if not mode_str:
        return default
    try:
        return AgentMode(mode_str.lower())
    except ValueError as err:
        print_error(f"Unknown mode '{mode_str}'. Choose from: ask, auto, plan")
        raise typer.Exit(1) from err


def build_agent(llm, tools: list, memory_ctx: str, agent_mode: AgentMode) -> "Agent":
    """Construct a configured Agent ready to run.

    The planner is stored on agent.planner so callers can call
    agent.planner.update_tools(tools) after adding/removing MCP servers.
    """
    mode_manager = ModeManager(default_mode=agent_mode)
    executor = ToolExecutor(tools=tools, mode_manager=mode_manager)
    planner = SimplePlanner(memory_context=memory_ctx, tools=tools)
    return Agent(
        provider=llm,
        planner=planner,
        executor=executor,
        tools=tools,
        mode_manager=mode_manager,
    )
