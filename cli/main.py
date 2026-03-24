import os
from pathlib import Path

import questionary
import typer
from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from questionary import Style as QStyle
from rich.panel import Panel
from rich.table import Table

from config.permissions import (
    PERMISSIONS_FILE,
    PermissionLevel,
    get_permissions,
    reset_permissions,
)
from config.settings import (
    CONFIG_FILE,
    ProviderConfig,
    Settings,
    keyring_available,
    save_config,
    set_api_key,
)
from core.agent import Agent
from core.executor import ToolExecutor
from core.mcp import MCPManager
from core.memory import MemoryManager, MemoryTool
from core.modes import AgentMode, ModeManager
from core.planner import Planner
from core.sessions import DEFAULT_MESSAGE_LIMIT, SessionManager
from core.skills import SkillManager
from core.tasks import get_task_manager, reset_task_manager
from providers import PROVIDER_ENV_VARS, PROVIDER_INFO, PROVIDERS, get_provider
from providers.base import ModelInfo
from schemas.message import Message
from tools.edit import EditTool
from tools.filesystem import FilesystemTool
from tools.grep import GrepTool
from tools.search import SearchTool
from tools.shell import ShellTool
from tools.task import TaskTool
from tools.terminal_session import TerminalSessionTool
from tools.websearch import WebFetchTool, WebSearchTool
from utils.logger import (
    get_console,
    print_error,
    print_info,
    print_panel,
    print_response,
    print_success,
    print_warning,
)

# Custom style for questionary prompts
QUESTIONARY_STYLE = QStyle(
    [
        ("qmark", "fg:#55aaff bold"),  # question mark
        ("question", "fg:#ffffff bold"),  # question text
        ("answer", "fg:#44ddaa bold"),  # confirmed answer
        ("pointer", "fg:#55ccff bold"),  # » arrow
        ("highlighted", "fg:#55ccff bold"),  # selected item text — matches pointer
        ("selected", "fg:#55ccff"),  # multi-select selected
        ("text", "fg:#bbbbbb"),  # unselected items
        ("disabled", "fg:#555555"),  # disabled items
        ("instruction", "fg:#666666 italic"),  # instruction hint
        ("separator", "fg:#444444"),  # separator lines
    ]
)

# ASCII Art Banner — clean, compact
BANNER = """
[bold cyan]  ╔╦╗┌─┐┬  ┬╔═╗┬─┐┌─┐┬ ┬
   ║║├┤ └┐┌┘║ ║├┬┘│  ├─┤
  ═╩╝└─┘ └┘ ╚═╝┴└─└─┘┴ ┴[/bold cyan]"""

BANNER_SMALL = "[bold cyan]DevOrch[/bold cyan]"

VERSION = "0.2.1"

# Slash commands with descriptions
SLASH_COMMANDS = {
    "/help": "Show available commands",
    "/mode": "Show or change mode (plan/auto/ask)",
    "/plan": "Switch to plan mode",
    "/auto": "Switch to auto mode",
    "/ask": "Switch to ask mode (default)",
    "/clear": "Clear conversation history",
    "/session": "Show current session info",
    "/config": "Show configuration settings",
    "/permissions": "Show permission settings",
    "/compact": "Summarize and compact history",
    "/models": "Browse and switch models (interactive)",
    "/model": "Switch model (/model <name> or interactive)",
    "/providers": "Browse and switch providers (interactive)",
    "/provider": "Switch provider (/provider <name> or interactive)",
    "/history": "Show conversation history",
    "/undo": "Undo last message",
    "/save": "Save conversation to file",
    "/status": "Show current provider, model, and mode",
    "/tasks": "Show current task list",
    "/memory": "Show saved memories",
    "/remember": "Save something to memory",
    "/forget": "Delete a memory",
    "/skills": "List available skills",
    "/skill": "Run a skill (e.g. /skill commit)",
    "/mcp": "Show MCP server status",
    "/auth": "Set or update API key for current/specified provider",
}

# Style for prompt_toolkit (including completion menu)
PROMPT_STYLE = Style.from_dict(
    {
        "prompt": "#55cc55 bold",
        "prompt-arrow": "#55cc55 bold",
        "": "#ffffff bold",  # input text — bright white, bold to stand out
        "command": "#66ccff bold",
        "description": "#888888",
        # Completion menu styling
        "completion-menu": "bg:#252530",
        "completion-menu.completion": "bg:#252530 #cccccc",
        "completion-menu.completion.current": "bg:#334466 #ffffff bold",
        "completion-menu.meta": "bg:#252530 #555555",
        "completion-menu.meta.current": "bg:#334466 #99bbdd",
        # Scrollbar
        "scrollbar.background": "bg:#2a2a3a",
        "scrollbar.button": "bg:#5588bb",
        # Bottom toolbar — near-invisible bg, just text
        "bottom-toolbar": "bg:#0e0e18 #556677",
        "bottom-toolbar.text": "bg:#0e0e18 #556677",
    }
)


def _xml_escape(text: str) -> str:
    """Escape text for use in prompt_toolkit HTML."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class SlashCommandCompleter(Completer):
    """Autocomplete for slash commands and skill shortcuts."""

    def __init__(self, skill_manager=None):
        self._skill_manager = skill_manager

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Only complete if starts with /
        if not text.startswith("/"):
            return

        # Get the partial command
        partial = text.lower()

        # Built-in slash commands
        for cmd, desc in SLASH_COMMANDS.items():
            if cmd.startswith(partial):
                # Pad command name for alignment (Gemini-like layout)
                padded_cmd = cmd[1:].ljust(16)  # strip / for display, pad
                safe_desc = _xml_escape(desc)
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display=HTML(
                        f"<command>{padded_cmd}</command><description>{safe_desc}</description>"
                    ),
                    display_meta=desc,
                )

        # Skill shortcuts (e.g. /commit, /review)
        if self._skill_manager:
            for skill in self._skill_manager.list_skills():
                skill_cmd = f"/{skill['name']}"
                if skill_cmd.startswith(partial) and skill_cmd not in SLASH_COMMANDS:
                    padded_cmd = skill["name"].ljust(16)
                    safe_desc = _xml_escape(skill["description"])
                    yield Completion(
                        skill_cmd,
                        start_position=-len(text),
                        display=HTML(
                            f"<command>{padded_cmd}</command><description>{safe_desc}</description>"
                        ),
                        display_meta=f"skill: {skill['description']}",
                    )


def print_banner(small: bool = False):
    """Print the DevOrch banner."""
    if small:
        console.print(f"\n  {BANNER_SMALL} [dim]v{VERSION}[/dim]\n")
    else:
        console.print(BANNER)
        console.print(f"  [dim]v{VERSION}[/dim]")
        console.print()


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


def _format_model_choice(
    model: ModelInfo, current_model: str = "", index: int = 0, max_name_len: int = 35
) -> questionary.Choice:
    """Build a rich questionary choice for a model."""
    is_current = model.id == current_model

    # Number + padded model name for alignment
    name_part = model.id.ljust(max_name_len)
    parts = [f" {index:>3}.  {name_part}"]

    # Metadata column
    meta = []
    if model.context_length:
        meta.append(f"{model.context_length:,} ctx")
    if model.description:
        meta.append(model.description[:40])
    if is_current:
        meta.append("● current")

    if meta:
        parts.append("  " + "  |  ".join(meta))

    display = "".join(parts)
    return questionary.Choice(display, value=model.id)


def _interactive_model_select(
    models: list[ModelInfo],
    provider_name: str,
    current_model: str = "",
    prompt_text: str | None = None,
) -> str | None:
    """Interactive model selection with search/filter support.

    Shows ALL models (no truncation), uses questionary fuzzy select
    for large lists, regular select for small ones.
    """
    if not models:
        print_warning("No models available.")
        return None

    prompt_text = prompt_text or f"Select model for {provider_name}:"

    # Compute max name length for aligned columns
    max_name = max(len(m.id) for m in models) if models else 30
    max_name = min(max_name + 2, 45)  # cap it so it doesn't get too wide

    choices = [
        _format_model_choice(m, current_model, i + 1, max_name) for i, m in enumerate(models)
    ]

    try:
        selected = questionary.select(
            prompt_text,
            choices=choices,
            style=QUESTIONARY_STYLE,
            instruction="(↑↓ navigate, Enter to select, Ctrl+C to cancel)",
        ).ask()
        return selected
    except (KeyboardInterrupt, EOFError):
        return None


def _interactive_provider_select(
    current_provider: str,
    current_settings: "Settings",
    prompt_text: str = "Select provider:",
) -> str | None:
    """Interactive provider selection with status indicators."""
    # Nice display names
    display_names = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "gemini": "Google Gemini",
        "groq": "Groq",
        "openrouter": "OpenRouter",
        "mistral": "Mistral",
        "together": "Together AI",
        "github_copilot": "GitHub Copilot",
        "deepseek": "DeepSeek",
        "kimi": "Kimi (Moonshot)",
        "custom": "Custom",
        "local": "Ollama",
        "lmstudio": "LM Studio",
    }

    cloud_choices = []
    local_choices = []
    num = 1

    for name, desc in PROVIDER_INFO.items():
        has_key = bool(current_settings.get_api_key(name))
        is_current = name == current_provider
        nice_name = display_names.get(name, name.title())
        short_desc = desc.split(" - ", 1)[1] if " - " in desc else desc

        # Status indicator
        if is_current:
            status = "● active"
        elif name in ("local", "lmstudio"):
            status = "local"
        elif has_key:
            status = "ready"
        else:
            status = "needs key"

        # Current model info
        model_info = ""
        if is_current:
            model_info = f"  [{current_settings.get_default_model(name)}]"

        display = f"{num:>2}.  {nice_name:<16} {short_desc:<40} ({status}){model_info}"
        choice = questionary.Choice(display, value=name)
        num += 1

        if name in ("local", "lmstudio"):
            local_choices.append(choice)
        else:
            cloud_choices.append(choice)

    provider_choices = cloud_choices + [questionary.Separator("── Local ──")] + local_choices

    try:
        return questionary.select(
            prompt_text,
            choices=provider_choices,
            style=QUESTIONARY_STYLE,
            instruction="(↑↓ navigate, Enter to select, Ctrl+C to cancel)",
        ).ask()
    except (KeyboardInterrupt, EOFError):
        return None


def _fuzzy_match_model(query: str, models: list[ModelInfo]) -> ModelInfo | None:
    """Find the best model match for a partial name query."""
    query_lower = query.lower()

    # Exact match
    for m in models:
        if m.id.lower() == query_lower:
            return m

    # Prefix match
    prefix_matches = [m for m in models if m.id.lower().startswith(query_lower)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]

    # Contains match
    contains_matches = [m for m in models if query_lower in m.id.lower()]
    if len(contains_matches) == 1:
        return contains_matches[0]

    # If multiple matches, return None (ambiguous)
    return None


class SimplePlanner(Planner):
    def __init__(self, memory_context: str = ""):
        self.memory_context = memory_context

    def plan(self, history: list[Message]) -> list[Message]:
        prompt = SYSTEM_PROMPT
        if self.memory_context:
            prompt += "\n" + self.memory_context
        system_prompt = Message(role="system", content=prompt)
        return [system_prompt] + history


# Main app with invoke_without_command=True so we can handle bare `devorch`
app = typer.Typer(
    help="DevOrch - Your AI Coding Assistant", invoke_without_command=True, no_args_is_help=False
)
sessions_app = typer.Typer(help="Manage chat sessions")
app.add_typer(sessions_app, name="sessions")

permissions_app = typer.Typer(help="Manage tool permissions")
app.add_typer(permissions_app, name="permissions")

console = get_console()


def has_any_provider_configured(settings: Settings) -> bool:
    """Check if any provider is configured (has API key or is local/lmstudio with model).

    Also checks if config file exists - if not, we need onboarding even if keys exist in keyring.
    """
    # If config file doesn't exist, run onboarding (even if keys exist in keyring)
    if not CONFIG_FILE.exists():
        return False

    # Check if any API-based provider has a key configured (keyring or env var)
    for name in PROVIDERS.keys():
        if name not in ("local", "lmstudio"):
            if settings.get_api_key(name):
                return True

    # Check if local/lmstudio is configured (has a saved model in config)
    for name in ("local", "lmstudio"):
        config = settings.providers.get(name)
        if config and config.default_model:
            return True

    return False


def run_onboarding() -> str | None:
    """Run first-time setup with interactive prompts. Returns the configured provider name or None."""
    print_banner()

    # Welcome panel
    console.print(
        Panel(
            "[bold]Welcome to DevOrch![/bold]\n\nLet's set up your AI provider to get started.",
            border_style="blue",
            padding=(1, 2),
        )
    )
    console.print()

    # Provider selection — built dynamically from registry
    cloud_providers = []
    local_providers = []
    for name, desc in PROVIDER_INFO.items():
        short_desc = desc.split(" - ", 1)[1] if " - " in desc else desc
        # Title-case the provider name for display
        display_name = {
            "openai": "OpenAI",
            "anthropic": "Anthropic",
            "gemini": "Google Gemini",
            "groq": "Groq",
            "openrouter": "OpenRouter",
            "mistral": "Mistral",
            "together": "Together AI",
            "github_copilot": "GitHub Copilot",
            "deepseek": "DeepSeek",
            "kimi": "Kimi (Moonshot)",
            "custom": "Custom",
            "local": "Ollama",
            "lmstudio": "LM Studio",
        }.get(name, name.title())

        if name in ("local", "lmstudio"):
            local_providers.append(
                questionary.Choice(f"{display_name} — {short_desc} (No API key)", value=name)
            )
        else:
            cloud_providers.append(questionary.Choice(f"{display_name} — {short_desc}", value=name))

    provider_choices = cloud_providers + [questionary.Separator()] + local_providers

    try:
        provider = questionary.select(
            "Select your AI provider:",
            choices=provider_choices,
            style=QUESTIONARY_STYLE,
            instruction="(↑↓ navigate, Enter to select, Ctrl+C to cancel)",
        ).ask()

        if not provider:
            return None

    except (KeyboardInterrupt, EOFError):
        return None

    if provider in ("local", "lmstudio"):
        print_success(f"{provider.title()} provider selected - no API key needed!")
        if provider == "local":
            print_info("Make sure Ollama is running at http://localhost:11434")
        else:
            print_info("Make sure LM Studio is running at http://localhost:1234")

        # Try to list available models and let user select
        settings = Settings.load()
        try:
            with console.status("[bold cyan]Fetching available models...", spinner="dots"):
                temp_provider = get_provider(provider)
                models = temp_provider.list_models()

            if models:
                selected_model = _interactive_model_select(
                    models, provider, prompt_text="Select a model:"
                )

                if selected_model:
                    if provider not in settings.providers:
                        settings.providers[provider] = ProviderConfig()
                    settings.providers[provider].default_model = selected_model
                    settings.default_provider = provider
                    save_config(settings)
                    print_success(f"Saved: provider={provider}, model={selected_model}")

        except Exception as e:
            print_warning(f"Could not list models: {e}")
            settings.default_provider = provider
            try:
                save_config(settings)
            except Exception:
                pass

        return provider

    # Get API key for cloud providers
    env_var = PROVIDER_ENV_VARS.get(provider, f"{provider.upper()}_API_KEY")

    console.print()
    console.print(
        Panel(
            f"[bold]Setting up {provider.title()}[/bold]\n\n"
            f"You'll need an API key from {provider.title()}.\n"
            f"Alternatively, set the [cyan]{env_var}[/cyan] environment variable.",
            border_style="yellow",
            padding=(0, 1),
        )
    )
    console.print()

    api_key = questionary.password(f"Enter your {provider} API key:", style=QUESTIONARY_STYLE).ask()

    if not api_key or not api_key.strip():
        print_error("API key cannot be empty.")
        return None

    api_key = api_key.strip()

    # Try to store in keyring
    if keyring_available():
        if set_api_key(provider, api_key):
            print_success("API key stored securely in system keychain!")
        else:
            print_warning("Could not store in keychain. Key will only be available this session.")
    else:
        print_warning("Keychain not available. Set the environment variable for persistence.")

    # Save as default provider
    settings = Settings.load()
    settings.default_provider = provider
    if provider not in settings.providers:
        settings.providers[provider] = ProviderConfig()
    settings.providers[provider].api_key = api_key

    # Let user select a model
    selected_model = None
    try:
        with console.status("[bold cyan]Fetching available models...", spinner="dots"):
            temp_provider = get_provider(provider, api_key=api_key)
            models = temp_provider.list_models()

        if models:
            selected_model = _interactive_model_select(
                models, provider, prompt_text="Select a model:"
            )

            if selected_model:
                settings.providers[provider].default_model = selected_model

    except Exception as e:
        print_warning(f"Could not fetch models: {e}")

    try:
        save_config(settings)
        if selected_model:
            print_success(f"Saved: provider={provider}, model={selected_model}")
        else:
            print_success(f"Default provider set to: {provider}")
    except Exception:
        pass  # Config save failed, but key is in memory

    console.print()
    console.print(
        Panel(
            "[bold green]Setup complete![/bold green]\n\n"
            "You're ready to start using DevOrch.\n"
            "Type your questions or commands, or use /help for available commands.",
            border_style="green",
            padding=(0, 1),
        )
    )

    return provider


def create_provider_safe(provider_name: str, model: str, settings: Settings):
    """Create provider, returning None if API key missing (for onboarding check)."""
    provider_name = provider_name.lower()

    if provider_name not in PROVIDERS:
        return None

    api_key = settings.get_api_key(provider_name)

    if provider_name != "local" and not api_key:
        return None

    if not model:
        model = settings.get_default_model(provider_name)

    kwargs = {}
    if provider_name == "local":
        base_url = settings.get_base_url(provider_name)
        if base_url:
            kwargs["base_url"] = base_url

    return get_provider(provider_name, model=model, api_key=api_key, **kwargs)


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


def start_repl(
    provider: str | None = None,
    model: str | None = None,
    resume: str | None = None,
    message_limit: int = DEFAULT_MESSAGE_LIMIT,
    show_banner: bool = True,
):
    """Start the interactive REPL session."""
    if show_banner:
        print_banner()

    settings = Settings.load()
    session_manager = SessionManager(message_limit=message_limit)

    # Reset task manager for new session
    reset_task_manager()

    context_summary = None

    # Handle session resumption
    if resume:
        try:
            session_info, messages = session_manager.load_session(resume)
            provider = session_info["provider"]
            model = session_info["model"]
            context_summary = session_info.get("summary")

            print_success(f"Resumed session: {resume}")
            print_info(f"Provider: {provider} | Model: {model} | Messages: {len(messages)}")

            if context_summary:
                print_info("Session has context from previous conversation")

        except ValueError as e:
            print_error(str(e))
            raise typer.Exit(1) from e
    else:
        messages = []

    if not provider:
        provider = settings.default_provider

    llm = create_provider(provider, model, settings)

    # Create new session if not resuming
    if not resume:
        session_manager.create_session(llm.name, llm.model)

    tools = [
        ShellTool(),
        TerminalSessionTool(),
        FilesystemTool(),
        SearchTool(),
        GrepTool(),
        EditTool(),
        TaskTool(),
        WebSearchTool(),
        WebFetchTool(),
        MemoryTool(),
    ]

    # Initialize memory manager and load context
    memory_manager = MemoryManager()
    memory_context = memory_manager.get_context_prompt()

    # Initialize skill manager
    skill_manager = SkillManager()

    # Initialize MCP servers from config
    mcp_manager = MCPManager()
    mcp_config = settings.mcp_servers or {}

    mcp_tools = []
    if mcp_config:
        with console.status("[bold cyan]Connecting MCP servers...", spinner="dots"):
            started = mcp_manager.load_from_config(mcp_config)
        if started:
            print_success(f"MCP servers connected: {', '.join(started)}")
            mcp_tools = mcp_manager.get_all_tools()
            tools.extend(mcp_tools)

    # Create mode manager (shared between agent and executor)
    mode_manager = ModeManager(default_mode=AgentMode.ASK)

    executor = ToolExecutor(tools=tools, require_confirmation=True, mode_manager=mode_manager)
    planner = SimplePlanner(memory_context=memory_context)

    def on_session_continue(new_session_id: str):
        print_info(f"Session continued: {new_session_id}")

    agent = Agent(
        provider=llm,
        planner=planner,
        executor=executor,
        tools=tools,
        session_manager=session_manager,
        on_session_continue=on_session_continue,
        mode_manager=mode_manager,
    )

    if messages:
        agent.set_history(messages)

    if context_summary:
        agent.set_context_summary(context_summary)

    # Get current working directory for display
    cwd = os.getcwd()
    cwd_display = cwd.replace(str(Path.home()), "~")

    # Show startup info — clean Gemini-like display
    mem_count = len(memory_manager.list_all())
    skill_count = len(skill_manager.list_skills())
    mcp_count = len(mcp_manager.servers)

    # Build status line items
    status_parts = [
        f"[bold white]Provider:[/bold white] [cyan]{llm.name}[/cyan]",
        f"[bold white]Model:[/bold white] [cyan]{llm.model}[/cyan]",
    ]
    extra_parts = []
    if mem_count:
        extra_parts.append(f"[dim]{mem_count} memories[/dim]")
    extra_parts.append(f"[dim]{skill_count} skills[/dim]")
    if mcp_count:
        extra_parts.append(f"[dim]{mcp_count} MCP[/dim]")

    console.print(
        Panel(
            " [dim]|[/dim] ".join(status_parts) + "\n" + " [dim]|[/dim] ".join(extra_parts),
            border_style="bright_black",
            padding=(0, 2),
        )
    )

    # Getting started tips
    console.print(
        "  [dim]Getting started:[/dim]\n"
        "  [dim]1.[/dim] Type [cyan]/[/cyan] to see all commands\n"
        "  [dim]2.[/dim] [cyan]/help[/cyan] for detailed help\n"
        "  [dim]3.[/dim] Ask coding questions or run commands\n"
        "  [dim]4.[/dim] [cyan]Ctrl+C[/cyan] to exit\n"
    )

    # Create completer for slash commands
    completer = SlashCommandCompleter(skill_manager=skill_manager)

    # Track current provider/model for switching
    current_llm = llm
    current_settings = settings

    def get_bottom_toolbar():
        """Clean bottom status bar."""
        mode_char = {"plan": "Plan", "auto": "Auto", "ask": "Ask"}.get(mode_manager.mode.value, "?")
        parts = [cwd_display, f"{current_llm.name}/{current_llm.model}", mode_char]
        mcp_n = len(mcp_manager.servers)
        if mcp_n:
            parts.append(f"MCP: {mcp_n}")
        return "  " + "     ".join(parts)

    while True:
        try:
            # Print a separator line above the prompt (Gemini-like)
            console.print("[dim]─[/dim]" * console.width, highlight=False)

            # Use prompt_toolkit with autocomplete and bottom toolbar
            user_input = pt_prompt(
                [("class:prompt-arrow", "> ")],
                completer=completer,
                complete_while_typing=True,
                style=PROMPT_STYLE,
                bottom_toolbar=get_bottom_toolbar,
            )

            if user_input.lower() in ("exit", "quit", "q"):
                mcp_manager.stop_all()
                print_info(f"Session saved: {session_manager.current_session_id}")
                break

            if user_input.strip() == "":
                continue

            # Handle slash commands
            if user_input.startswith("/"):
                cmd_parts = user_input[1:].strip().split(maxsplit=1)
                cmd = cmd_parts[0].lower() if cmd_parts else ""
                cmd_arg = cmd_parts[1] if len(cmd_parts) > 1 else None

                if cmd == "help":
                    console.print()

                    # Group commands by category
                    categories = {
                        "Modes": ["/mode", "/plan", "/auto", "/ask"],
                        "Provider & Model": ["/providers", "/provider", "/models", "/model"],
                        "Session": ["/session", "/history", "/undo", "/clear", "/compact", "/save"],
                        "Memory": ["/memory", "/remember", "/forget"],
                        "Skills": ["/skills", "/skill"],
                        "Tools & Config": [
                            "/tasks",
                            "/config",
                            "/permissions",
                            "/mcp",
                            "/status",
                            "/auth",
                        ],
                    }

                    for category, cmds in categories.items():
                        console.print(f"  [bold]{category}[/bold]")
                        for slash_cmd in cmds:
                            desc = SLASH_COMMANDS.get(slash_cmd, "")
                            console.print(f"    [cyan]{slash_cmd:<16}[/cyan] {desc}")
                        console.print()

                    console.print(f"    [cyan]{'exit':<16}[/cyan] Exit DevOrch")

                    # Show available skills as shortcuts
                    skill_names = [s["name"] for s in skill_manager.list_skills()]
                    if skill_names:
                        console.print(
                            f"\n  [bold]Skill Shortcuts:[/bold]  /{', /'.join(skill_names)}"
                        )

                    console.print("\n  [bold]Modes:[/bold]")
                    console.print(
                        "    [yellow]PLAN[/yellow] - Shows plan before executing, asks for approval"
                    )
                    console.print(
                        "    [green]AUTO[/green] - Executes tools automatically (trusted mode)"
                    )
                    console.print(
                        "    [blue]ASK[/blue]  - Asks before each tool execution (default)"
                    )
                    console.print(
                        "\n[dim]  Tip: Type / for autocomplete | /model and /provider support partial match[/dim]\n"
                    )
                    continue

                elif cmd == "mode":
                    if cmd_arg:
                        mode_name = cmd_arg.lower()
                    else:
                        # Interactive mode selection
                        mode_choices = [
                            questionary.Choice(
                                f" 1.  {'[current] ' if mode_manager.mode == AgentMode.PLAN else ''}PLAN - Shows plan before executing, asks for approval",
                                value="plan",
                            ),
                            questionary.Choice(
                                f" 2.  {'[current] ' if mode_manager.mode == AgentMode.AUTO else ''}AUTO - Executes tools automatically (trusted mode)",
                                value="auto",
                            ),
                            questionary.Choice(
                                f" 3.  {'[current] ' if mode_manager.mode == AgentMode.ASK else ''}ASK - Asks before each tool execution (default)",
                                value="ask",
                            ),
                        ]
                        try:
                            mode_name = questionary.select(
                                "Select mode:",
                                choices=mode_choices,
                                style=QUESTIONARY_STYLE,
                                instruction="(↑↓ navigate, Enter to select, Ctrl+C to cancel)",
                            ).ask()
                            if not mode_name:
                                continue
                        except (KeyboardInterrupt, EOFError):
                            continue

                    if mode_name in ("plan", "auto", "ask"):
                        mode_manager.mode = AgentMode(mode_name)
                        print_success(f"Switched to {mode_name.upper()} mode")
                        console.print(f"  [dim]{mode_manager.get_mode_description()}[/dim]")
                    else:
                        print_error(f"Unknown mode: {mode_name}")
                    continue

                elif cmd == "plan":
                    mode_manager.mode = AgentMode.PLAN
                    print_success("Switched to PLAN mode")
                    console.print("  [dim]I'll show you the plan before executing anything[/dim]")
                    continue

                elif cmd == "auto":
                    mode_manager.mode = AgentMode.AUTO
                    print_success("Switched to AUTO mode")
                    console.print(
                        "  [dim]I'll execute tools automatically (dangerous commands still blocked)[/dim]"
                    )
                    continue

                elif cmd == "ask":
                    mode_manager.mode = AgentMode.ASK
                    print_success("Switched to ASK mode")
                    console.print("  [dim]I'll ask before each tool execution[/dim]")
                    continue

                elif cmd == "clear":
                    agent.history = []
                    print_success("Conversation cleared.")
                    continue

                elif cmd == "status":
                    console.print("\n[bold]Status[/bold]")
                    console.print(f"  [dim]Provider:[/dim]  [cyan]{current_llm.name}[/cyan]")
                    console.print(f"  [dim]Model:[/dim]     [cyan]{current_llm.model}[/cyan]")
                    console.print(f"  [dim]Mode:[/dim]      {mode_manager.get_mode_display()}")
                    console.print(f"  [dim]Session:[/dim]   {session_manager.current_session_id}")
                    console.print(f"  [dim]Messages:[/dim]  {len(agent.history)}")
                    _mem_count = len(memory_manager.list_all())
                    console.print(f"  [dim]Memories:[/dim]  {_mem_count}")
                    console.print(f"  [dim]Skills:[/dim]    {len(skill_manager.list_skills())}")
                    _mcp_count = len(mcp_manager.servers)
                    if _mcp_count:
                        console.print(f"  [dim]MCP:[/dim]       {_mcp_count} server(s)")
                    console.print()
                    continue

                elif cmd == "session":
                    console.print("\n[bold]Current Session[/bold]")
                    print_info(f"Session ID: {session_manager.current_session_id}")
                    print_info(f"Messages: {len(agent.history)}")
                    print_info(f"Provider: {current_llm.name}")
                    print_info(f"Model: {current_llm.model}")
                    console.print(f"  [dim]Mode:[/dim] {mode_manager.get_mode_display()}")
                    console.print()
                    continue

                elif cmd == "config":
                    console.print("\n[bold]Configuration[/bold]")
                    print_info(f"Provider: {current_llm.name}")
                    print_info(f"Model: {current_llm.model}")
                    print_info(f"Session limit: {session_manager.message_limit} messages")
                    print_info(
                        f"Keyring: {'available' if keyring_available() else 'not available'}"
                    )
                    console.print()
                    continue

                elif cmd == "auth":
                    # /auth [provider] — set or update API key
                    target_provider = cmd_arg.lower() if cmd_arg else current_llm.name
                    if target_provider in ("local", "ollama", "lmstudio"):
                        print_info(f"{target_provider} doesn't need an API key.")
                        continue

                    env_var = PROVIDER_ENV_VARS.get(
                        target_provider, f"{target_provider.upper()}_API_KEY"
                    )
                    console.print(
                        Panel(
                            f"[bold]Set API key for {target_provider}[/bold]\n"
                            f"[dim]Or set {env_var} environment variable[/dim]",
                            border_style="cyan",
                        )
                    )

                    try:
                        api_key = questionary.password(
                            f"Enter API key for {target_provider}:",
                            style=QUESTIONARY_STYLE,
                        ).ask()

                        if not api_key or not api_key.strip():
                            print_error("API key cannot be empty.")
                            continue

                        entered_key = api_key.strip()

                        # Store in keyring
                        if keyring_available():
                            set_api_key(target_provider, entered_key)
                            print_success("API key stored in keychain!")
                        else:
                            print_warning("Keyring not available — key stored in memory only.")

                        # Update settings
                        if target_provider not in current_settings.providers:
                            current_settings.providers[target_provider] = ProviderConfig()
                        current_settings.providers[target_provider].api_key = entered_key

                        # If updating the current provider, reload it
                        if target_provider == current_llm.name:
                            try:
                                new_llm = get_provider(
                                    target_provider, model=current_llm.model, api_key=entered_key
                                )
                                current_llm = new_llm
                                agent.provider = new_llm
                                print_success(f"Reloaded {target_provider} with new key.")
                            except Exception as e:
                                print_error(f"Key saved but failed to reload: {e}")
                        else:
                            print_success(f"API key saved for {target_provider}.")
                    except (KeyboardInterrupt, EOFError):
                        console.print("\nCancelled.")
                    continue

                elif cmd == "permissions":
                    perms = get_permissions()
                    console.print("\n[bold]Tool Permissions:[/bold]")
                    for tool_name, perm in perms.tools.items():
                        level_color = {"allow": "green", "deny": "red", "ask": "yellow"}.get(
                            perm.level.value, "white"
                        )
                        console.print(
                            f"  {tool_name}: [{level_color}]{perm.level.value}[/{level_color}]"
                        )
                    if perms.session_allowed:
                        console.print(
                            f"\n[green]Session allowed:[/green] {len(perms.session_allowed)} patterns"
                        )
                    console.print()
                    continue

                elif cmd == "compact":
                    print_info("Compacting conversation history...")
                    summary = agent._generate_summary()
                    agent.history = []
                    agent.set_context_summary(summary)
                    print_success("History compacted. Summary preserved.")
                    continue

                elif cmd in ("models", "model"):
                    selected_model = cmd_arg

                    try:
                        with console.status("[cyan]Fetching models...", spinner="dots"):
                            models = current_llm.list_models()
                    except Exception as e:
                        print_error(f"Failed to fetch models: {e}")
                        continue

                    if not models:
                        print_warning("No models available")
                        continue

                    if selected_model:
                        # User typed /model <name> — try fuzzy match
                        match = _fuzzy_match_model(selected_model, models)
                        if match:
                            selected_model = match.id
                            if match.id != cmd_arg:
                                print_info(f"Matched: {match.id}")
                        else:
                            # Check if there are multiple partial matches
                            partial = [m for m in models if cmd_arg.lower() in m.id.lower()]
                            if partial:
                                console.print(
                                    f"\n[yellow]Multiple matches for '{cmd_arg}':[/yellow]"
                                )
                                selected_model = _interactive_model_select(
                                    partial,
                                    current_llm.name,
                                    current_llm.model,
                                    prompt_text="Select from matches:",
                                )
                                if not selected_model:
                                    continue
                            else:
                                # No match at all — use it as-is (user might know what they want)
                                selected_model = cmd_arg
                    else:
                        # Interactive selection — show ALL models
                        selected_model = _interactive_model_select(
                            models,
                            current_llm.name,
                            current_llm.model,
                        )
                        if not selected_model:
                            continue

                    try:
                        # Build kwargs for provider (include base_url for local)
                        provider_kwargs = {}
                        if current_llm.name == "local":
                            base_url = current_settings.get_base_url(current_llm.name)
                            if base_url:
                                provider_kwargs["base_url"] = base_url

                        # Get API key - prefer current provider's key, then settings
                        api_key = getattr(
                            current_llm, "api_key", None
                        ) or current_settings.get_api_key(current_llm.name)

                        new_llm = get_provider(
                            current_llm.name,
                            model=selected_model,
                            api_key=api_key,
                            **provider_kwargs,
                        )
                        current_llm = new_llm
                        agent.provider = new_llm

                        # Save model selection to settings
                        try:
                            if current_llm.name not in current_settings.providers:
                                current_settings.providers[current_llm.name] = ProviderConfig()
                            current_settings.providers[
                                current_llm.name
                            ].default_model = selected_model
                            save_config(current_settings)
                            print_success(f"Switched to model: {selected_model}")
                        except Exception:
                            print_success(f"Switched to model: {selected_model}")
                    except Exception as e:
                        print_error(f"Failed to switch model: {e}")
                    continue

                elif cmd in ("providers", "provider"):
                    if cmd_arg:
                        new_provider = cmd_arg.lower()
                    else:
                        new_provider = _interactive_provider_select(
                            current_llm.name, current_settings
                        )
                        if not new_provider:
                            continue

                    if new_provider not in PROVIDERS:
                        print_error(f"Unknown provider: {new_provider}")
                        continue

                    # Check if provider needs API key and doesn't have one
                    needs_key = new_provider not in ("local", "lmstudio")
                    has_key = bool(current_settings.get_api_key(new_provider))

                    entered_key = None
                    selected_model = None

                    if needs_key and not has_key:
                        # Prompt for API key with questionary
                        env_var = PROVIDER_ENV_VARS.get(
                            new_provider, f"{new_provider.upper()}_API_KEY"
                        )
                        console.print(
                            Panel(
                                f"[bold]Setting up {new_provider}[/bold]\n"
                                f"[dim]You can also set {env_var} environment variable[/dim]",
                                border_style="yellow",
                            )
                        )

                        try:
                            api_key = questionary.password(
                                f"Enter your {new_provider} API key:", style=QUESTIONARY_STYLE
                            ).ask()

                            if api_key and api_key.strip():
                                entered_key = api_key.strip()

                                # Store in keyring
                                if keyring_available():
                                    set_api_key(new_provider, entered_key)
                                    print_success("API key stored in keychain!")

                                # Update settings
                                if new_provider not in current_settings.providers:
                                    current_settings.providers[new_provider] = ProviderConfig()
                                current_settings.providers[new_provider].api_key = entered_key

                                # Offer model selection
                                try:
                                    with console.status("[cyan]Fetching models...", spinner="dots"):
                                        temp_llm = get_provider(new_provider, api_key=entered_key)
                                        models = temp_llm.list_models()
                                    if models:
                                        selected_model = _interactive_model_select(
                                            models,
                                            new_provider,
                                            prompt_text="Select a model:",
                                        )
                                        if selected_model:
                                            current_settings.providers[
                                                new_provider
                                            ].default_model = selected_model
                                except Exception:
                                    pass  # Model selection is optional
                            else:
                                print_error("API key cannot be empty.")
                                continue
                        except (KeyboardInterrupt, EOFError):
                            console.print("\nCancelled.")
                            continue

                    try:
                        # Use entered key directly if we just got it, otherwise use settings
                        if entered_key:
                            new_llm = get_provider(
                                new_provider, model=selected_model, api_key=entered_key
                            )
                        else:
                            new_llm = create_provider(new_provider, None, current_settings)
                        current_llm = new_llm
                        agent.provider = new_llm

                        # Save provider selection to settings
                        try:
                            current_settings.default_provider = new_provider
                            save_config(current_settings)
                            print_success(f"Switched to: {new_provider} ({new_llm.model})")
                        except Exception:
                            print_success(f"Switched to: {new_provider} ({new_llm.model})")
                    except Exception as e:
                        print_error(f"Failed to switch provider: {e}")
                    continue

                elif cmd == "history":
                    console.print("\n[bold]Conversation History[/bold]")
                    if not agent.history:
                        print_info("No messages yet.")
                    else:
                        for _i, msg in enumerate(agent.history[-10:], 1):
                            role_color = {
                                "user": "green",
                                "assistant": "blue",
                                "tool": "yellow",
                            }.get(msg.role, "white")
                            content_preview = (
                                (msg.content[:80] + "...") if len(msg.content) > 80 else msg.content
                            )
                            console.print(
                                f"  [{role_color}]{msg.role}[/{role_color}]: {content_preview}"
                            )
                        if len(agent.history) > 10:
                            console.print(
                                f"  [dim]... and {len(agent.history) - 10} more messages[/dim]"
                            )
                    console.print()
                    continue

                elif cmd == "undo":
                    if agent.history:
                        # Remove last user message and any following assistant/tool messages
                        removed = 0
                        while agent.history and agent.history[-1].role != "user":
                            agent.history.pop()
                            removed += 1
                        if agent.history and agent.history[-1].role == "user":
                            agent.history.pop()
                            removed += 1
                        print_success(f"Removed {removed} message(s)")
                    else:
                        print_warning("No messages to undo")
                    continue

                elif cmd == "save":
                    filename = (
                        cmd_arg or f"devorch_session_{session_manager.current_session_id}.txt"
                    )
                    try:
                        with open(filename, "w") as f:
                            for msg in agent.history:
                                f.write(f"[{msg.role}]\n{msg.content}\n\n")
                        print_success(f"Saved to: {filename}")
                    except Exception as e:
                        print_error(f"Failed to save: {e}")
                    continue

                elif cmd == "tasks":
                    task_manager = get_task_manager()
                    if task_manager.task_list.total_count == 0:
                        print_info("No tasks in progress.")
                    else:
                        panel = task_manager._create_panel()
                        console.print(panel)
                    continue

                elif cmd == "memory":
                    memories = memory_manager.list_all()
                    if not memories:
                        print_info("No memories saved yet.")
                    else:
                        console.print(f"\n[bold]Saved Memories ({len(memories)}):[/bold]")
                        for mem in memories:
                            type_color = {
                                "user": "cyan",
                                "feedback": "yellow",
                                "project": "green",
                                "reference": "blue",
                            }.get(mem["type"], "white")
                            console.print(
                                f"  [{type_color}][{mem['type']}][/{type_color}] "
                                f"[bold]{mem['name']}[/bold]"
                            )
                            console.print(f"    [dim]{mem['description']}[/dim]")
                            console.print(f"    [dim]File: {mem['filename']}[/dim]")
                    console.print()
                    continue

                elif cmd == "remember":
                    if not cmd_arg:
                        print_warning("Usage: /remember <what to remember>")
                        print_info("Example: /remember I prefer tabs over spaces")
                        continue
                    # Feed it to the agent as a memory save instruction
                    remember_prompt = (
                        f'The user wants you to remember this: "{cmd_arg}"\n'
                        f"Save this to memory using the memory tool. Choose the appropriate "
                        f"memory type (user/feedback/project/reference) and write a clear "
                        f"name and description."
                    )
                    result = agent.run(remember_prompt, max_iterations=5)
                    print_response(result)
                    continue

                elif cmd == "forget":
                    if not cmd_arg:
                        memories = memory_manager.list_all()
                        if not memories:
                            print_info("No memories to forget.")
                            continue
                        # Let user pick which to delete
                        memory_choices = [
                            questionary.Choice(
                                f"[{mem['type']}] {mem['name']}",
                                value=mem["filename"],
                            )
                            for mem in memories
                        ]
                        try:
                            to_delete = questionary.select(
                                "Select memory to forget:",
                                choices=memory_choices,
                                style=QUESTIONARY_STYLE,
                            ).ask()
                            if to_delete and memory_manager.delete(to_delete):
                                print_success(f"Forgot: {to_delete}")
                            else:
                                print_info("Cancelled.")
                        except (KeyboardInterrupt, EOFError):
                            continue
                    else:
                        # Try to find and delete by name match
                        memories = memory_manager.search(query=cmd_arg)
                        if memories:
                            if memory_manager.delete(memories[0]["filename"]):
                                print_success(f"Forgot: {memories[0]['name']}")
                            else:
                                print_error("Failed to delete memory.")
                        else:
                            print_warning(f"No memory found matching '{cmd_arg}'")
                    continue

                elif cmd == "skills":
                    skills = skill_manager.list_skills()
                    console.print(f"\n[bold]Available Skills ({len(skills)}):[/bold]")
                    for sk in skills:
                        source = (
                            "[dim](built-in)[/dim]"
                            if sk["source"] == "built-in"
                            else "[dim](custom)[/dim]"
                        )
                        console.print(
                            f"  [cyan]/{sk['name']}[/cyan] - {sk['description']} {source}"
                        )
                    console.print(
                        "\n[dim]Use /skill <name> to run a skill. "
                        "Add custom skills in ~/.devorch/skills/[/dim]\n"
                    )
                    continue

                elif cmd == "skill":
                    if not cmd_arg:
                        print_warning("Usage: /skill <name>")
                        print_info("Use /skills to see available skills")
                        continue
                    skill_name = cmd_arg.split()[0]
                    skill = skill_manager.get(skill_name)
                    if not skill:
                        print_error(f"Unknown skill: {skill_name}")
                        print_info("Use /skills to see available skills")
                        continue
                    console.print(
                        f"  [dim]Running skill:[/dim] [cyan]{skill_name}[/cyan] - {skill['description']}"
                    )
                    result = agent.run(skill["prompt"], max_iterations=15)
                    print_response(result)
                    continue

                elif cmd == "mcp":
                    servers = mcp_manager.list_servers()
                    if not servers:
                        console.print("\n[bold]MCP Servers:[/bold] None connected")
                        console.print("[dim]Configure MCP servers in ~/.devorch/config.yaml:[/dim]")
                        console.print(
                            "[dim]  mcp_servers:\n"
                            "    my-server:\n"
                            "      command: npx\n"
                            '      args: ["-y", "@modelcontextprotocol/server-xxx"][/dim]\n'
                        )
                    else:
                        console.print(f"\n[bold]MCP Servers ({len(servers)}):[/bold]")
                        for srv in servers:
                            status = (
                                "[green]running[/green]" if srv["running"] else "[red]stopped[/red]"
                            )
                            console.print(f"  [cyan]{srv['name']}[/cyan] - {status}")
                            if srv["tools"]:
                                console.print(f"    Tools: {', '.join(srv['tools'])}")
                    console.print()
                    continue

                # Also handle direct skill invocation (e.g. /commit, /review)
                elif cmd in [s["name"] for s in skill_manager.list_skills()]:
                    skill = skill_manager.get(cmd)
                    if skill:
                        console.print(
                            f"  [dim]Running skill:[/dim] [cyan]{cmd}[/cyan] - {skill['description']}"
                        )
                        result = agent.run(skill["prompt"], max_iterations=15)
                        print_response(result)
                        continue

                else:
                    print_warning(f"Unknown command: /{cmd}")
                    print_info("Type /help to see available commands")
                    continue

            result = agent.run(user_input, max_iterations=15)
            print_response(result)

        except (typer.Abort, EOFError):
            mcp_manager.stop_all()
            print_info(f"\nSession saved: {session_manager.current_session_id}")
            break
        except KeyboardInterrupt:
            mcp_manager.stop_all()
            console.print()
            print_info(f"Session saved: {session_manager.current_session_id}")
            break
        except Exception as e:
            error_str = str(e).lower()
            print_error(str(e))

            # Provide helpful hints for common errors
            if "401" in error_str or "unauthorized" in error_str or "authentication" in error_str:
                console.print("[dim]  Tip: Your API key may be invalid. Try:[/dim]")
                console.print("[dim]  - /provider <name> to switch providers[/dim]")
                console.print(
                    f"[dim]  - devorch set-key {current_llm.name} to update the key[/dim]"
                )
            elif (
                "402" in error_str
                or "payment" in error_str
                or "quota" in error_str
                or "rate" in error_str
            ):
                console.print("[dim]  Tip: You may have exceeded your quota or rate limit.[/dim]")
                console.print("[dim]  - /provider <name> to switch to another provider[/dim]")
            elif "connection" in error_str or "timeout" in error_str or "network" in error_str:
                console.print("[dim]  Tip: Network error. Check your connection.[/dim]")
                if current_llm.name == "local":
                    console.print("[dim]  - Make sure Ollama is running: ollama serve[/dim]")


@app.callback()
def main_callback(
    ctx: typer.Context,
    provider: str = typer.Option(None, "--provider", "-p", help="LLM Provider"),
    model: str = typer.Option(None, "--model", "-m", help="Model name"),
    resume: str = typer.Option(None, "--resume", "-r", help="Resume session by ID"),
):
    """
    DevOrch - Your AI Coding Assistant

    Just run 'devorch' to start chatting!
    """
    # If a subcommand is being invoked, don't run the default behavior
    if ctx.invoked_subcommand is not None:
        return

    # No subcommand - run the default REPL behavior
    settings = Settings.load()

    # Check if we need onboarding
    if not has_any_provider_configured(settings):
        configured_provider = run_onboarding()
        if not configured_provider:
            raise typer.Exit(1)
        # Reload settings after onboarding
        settings = Settings.load()
        provider = configured_provider

    # Start REPL
    start_repl(provider=provider, model=model, resume=resume)


@app.command()
def chat(
    provider: str = typer.Option(None, "--provider", "-p", help="LLM Provider"),
    model: str = typer.Option(None, "--model", "-m", help="Model name"),
    resume: str = typer.Option(None, "--resume", "-r", help="Resume session by ID"),
    message_limit: int = typer.Option(
        DEFAULT_MESSAGE_LIMIT, "--limit", "-l", help="Messages before auto-summarization"
    ),
):
    """
    Start an interactive chat session (alias for running devorch directly).
    """
    settings = Settings.load()

    if not has_any_provider_configured(settings):
        configured_provider = run_onboarding()
        if not configured_provider:
            raise typer.Exit(1)
        settings = Settings.load()
        provider = configured_provider

    start_repl(provider=provider, model=model, resume=resume, message_limit=message_limit)


@app.command()
def ask(
    prompt: str = typer.Argument(..., help="The prompt or question for DevOrch"),
    provider: str = typer.Option(None, "--provider", "-p", help="LLM Provider"),
    model: str = typer.Option(None, "--model", "-m", help="Model name"),
):
    """
    Ask DevOrch a single question (non-interactive).
    """
    settings = Settings.load()

    if not provider:
        provider = settings.default_provider

    llm = create_provider(provider, model, settings)

    tools = [
        ShellTool(),
        TerminalSessionTool(),
        FilesystemTool(),
        SearchTool(),
        GrepTool(),
        EditTool(),
        TaskTool(),
        WebSearchTool(),
        WebFetchTool(),
        MemoryTool(),
    ]

    memory_mgr = MemoryManager()
    memory_ctx = memory_mgr.get_context_prompt()

    executor = ToolExecutor(tools=tools)
    planner = SimplePlanner(memory_context=memory_ctx)

    agent = Agent(provider=llm, planner=planner, executor=executor, tools=tools)

    console.print(f"[dim]Using {llm.name}/{llm.model}[/dim]")
    try:
        result = agent.run(prompt, max_iterations=15)
        print_panel(result, title="DevOrch", border_style="cyan")
    except Exception as e:
        print_error(str(e))


@app.command()
def config():
    """
    Show current configuration.
    """
    settings = Settings.load()

    console.print("\n[bold]DevOrch Configuration[/bold]\n")
    console.print(f"Default Provider: [cyan]{settings.default_provider}[/cyan]")
    console.print(
        f"Keyring Available: {'[green]yes[/green]' if keyring_available() else '[yellow]no[/yellow]'}"
    )
    console.print("\n[bold]Providers:[/bold]")

    for name in PROVIDERS.keys():
        provider_config = settings.providers.get(name)
        if provider_config:
            if name == "local":
                key_status = "[dim]not required[/dim]"
            elif provider_config.api_key:
                if provider_config.key_encrypted:
                    key_status = "[green]configured (encrypted)[/green]"
                else:
                    key_status = "[green]configured[/green]"
            else:
                key_status = "[yellow]not set[/yellow]"
            model = provider_config.default_model or "default"
            console.print(f"  [bold]{name}[/bold]: {model} (API key: {key_status})")


@app.command("set-key")
def set_key(
    provider: str = typer.Argument(..., help="Provider name (openai, anthropic, gemini)"),
    set_default: bool = typer.Option(
        True, "--default/--no-default", help="Set as default provider"
    ),
):
    """
    Securely store an API key for a provider.
    """
    if provider.lower() not in PROVIDERS:
        print_error(f"Unknown provider '{provider}'. Available: {', '.join(PROVIDERS.keys())}")
        raise typer.Exit(1)

    if provider.lower() == "local":
        print_warning("Local provider doesn't require an API key.")
        raise typer.Exit(0)

    if not keyring_available():
        print_error("Keyring is not available on this system.")
        print_error("Please set API keys via environment variables instead.")
        raise typer.Exit(1)

    api_key = typer.prompt(f"Enter API key for {provider}", hide_input=True)

    if not api_key.strip():
        print_error("API key cannot be empty.")
        raise typer.Exit(1)

    if set_api_key(provider.lower(), api_key.strip()):
        print_success(f"API key for {provider} stored securely.")

        # Also set as default provider
        if set_default:
            settings = Settings.load()
            settings.default_provider = provider.lower()
            try:
                save_config(settings)
                print_success(f"Set {provider} as default provider.")
            except Exception:
                print_warning(
                    f"Key stored but couldn't save as default. Use: devorch -p {provider}"
                )
    else:
        print_error("Failed to store API key.")
        raise typer.Exit(1)


@app.command()
def providers():
    """
    List available providers.
    """
    console.print("\n[bold]Available Providers:[/bold]\n")
    for name in PROVIDERS.keys():
        console.print(f"  - {name}")


# Session commands
@sessions_app.command("list")
def sessions_list(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of sessions to show"),
):
    """
    List recent chat sessions.
    """
    session_manager = SessionManager()
    sessions = session_manager.list_sessions(limit=limit)

    if not sessions:
        print_info("No sessions found.")
        return

    table = Table(title="Chat Sessions")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Provider", style="green")
    table.add_column("Model", style="blue")
    table.add_column("Msgs", justify="right")
    table.add_column("Parent", style="dim")
    table.add_column("Updated", style="dim")

    for session in sessions:
        parent = session.get("parent_session_id") or "-"
        table.add_row(
            session["id"],
            (session["name"] or "-")[:20],
            session["provider"],
            session["model"][:15],
            str(session["message_count"]),
            parent[:8] if parent != "-" else "-",
            session["updated_at"][:16],
        )

    console.print(table)


@sessions_app.command("show")
def sessions_show(session_id: str = typer.Argument(..., help="Session ID to show details")):
    """
    Show details of a specific session.
    """
    session_manager = SessionManager()

    try:
        session_info, messages = session_manager.load_session(session_id)
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1) from e

    console.print(f"\n[bold]Session: {session_id}[/bold]")
    console.print(f"Name: {session_info.get('name', '-')}")
    console.print(f"Provider: {session_info['provider']}")
    console.print(f"Model: {session_info['model']}")
    console.print(f"Messages: {len(messages)}")

    if session_info.get("parent_session_id"):
        console.print(f"Parent: {session_info['parent_session_id']}")

    if session_info.get("summary"):
        console.print("\n[bold]Context Summary:[/bold]")
        summary = session_info["summary"]
        print_panel(summary[:500] + "..." if len(summary) > 500 else summary, border_style="dim")


@sessions_app.command("delete")
def sessions_delete(session_id: str = typer.Argument(..., help="Session ID to delete")):
    """
    Delete a chat session.
    """
    session_manager = SessionManager()

    if not session_manager.session_exists(session_id):
        print_error(f"Session '{session_id}' not found.")
        raise typer.Exit(1)

    if session_manager.delete_session(session_id):
        print_success(f"Session '{session_id}' deleted.")
    else:
        print_error("Failed to delete session.")
        raise typer.Exit(1)


@sessions_app.command("clear")
def sessions_clear(force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")):
    """
    Delete all chat sessions.
    """
    session_manager = SessionManager()
    sessions = session_manager.list_sessions(limit=1000)

    if not sessions:
        print_info("No sessions to delete.")
        return

    if not force:
        confirm = typer.confirm(f"Delete {len(sessions)} sessions?")
        if not confirm:
            print_warning("Cancelled.")
            return

    deleted = 0
    for session in sessions:
        if session_manager.delete_session(session["id"]):
            deleted += 1

    print_success(f"Deleted {deleted} sessions.")


# Permission commands
@permissions_app.command("list")
def permissions_list():
    """
    Show current permission settings.
    """
    permissions = get_permissions()

    console.print("\n[bold]Tool Permissions[/bold]\n")

    for tool_name, perm in permissions.tools.items():
        level_color = {
            PermissionLevel.ALLOW: "green",
            PermissionLevel.DENY: "red",
            PermissionLevel.ASK: "yellow",
        }.get(perm.level, "white")

        console.print(
            f"[bold]{tool_name}[/bold]: [{level_color}]{perm.level.value}[/{level_color}]"
        )

        if perm.allowed_patterns:
            console.print(f"  [green]Allowed patterns:[/green] {len(perm.allowed_patterns)}")
            for p in perm.allowed_patterns[:5]:
                console.print(f"    - {p}")
            if len(perm.allowed_patterns) > 5:
                console.print(f"    [dim]... and {len(perm.allowed_patterns) - 5} more[/dim]")

        if perm.denied_patterns:
            console.print(f"  [red]Denied patterns:[/red] {len(perm.denied_patterns)}")
            for p in perm.denied_patterns[:3]:
                console.print(f"    - {p}")

    # Session permissions
    if permissions.session_allowed or permissions.session_denied:
        console.print("\n[bold]Session Permissions (temporary)[/bold]")
        if permissions.session_allowed:
            console.print(f"  [green]Allowed:[/green] {', '.join(permissions.session_allowed)}")
        if permissions.session_denied:
            console.print(f"  [red]Denied:[/red] {', '.join(permissions.session_denied)}")

    console.print(f"\n[dim]Config file: {PERMISSIONS_FILE}[/dim]")


@permissions_app.command("allow")
def permissions_allow(
    tool: str = typer.Argument(..., help="Tool name (shell, filesystem)"),
    pattern: str = typer.Argument(..., help="Command pattern to allow (e.g., 'git *')"),
):
    """
    Add a pattern to the allowed list for a tool.
    """
    permissions = get_permissions()
    permissions.add_allowed_pattern(tool, pattern, session_only=False)
    print_success(f"Added to allowed patterns for {tool}: {pattern}")


@permissions_app.command("deny")
def permissions_deny(
    tool: str = typer.Argument(..., help="Tool name (shell, filesystem)"),
    pattern: str = typer.Argument(..., help="Command pattern to deny"),
):
    """
    Add a pattern to the denied list for a tool.
    """
    permissions = get_permissions()
    permissions.add_denied_pattern(tool, pattern, session_only=False)
    print_success(f"Added to denied patterns for {tool}: {pattern}")


@permissions_app.command("set")
def permissions_set(
    tool: str = typer.Argument(..., help="Tool name (shell, filesystem, search)"),
    level: str = typer.Argument(..., help="Permission level (allow, deny, ask)"),
):
    """
    Set the default permission level for a tool.
    """
    try:
        perm_level = PermissionLevel(level.lower())
    except ValueError:
        print_error(f"Invalid level: {level}. Use: allow, deny, or ask")
        raise typer.Exit(1) from None

    permissions = get_permissions()
    permissions.set_tool_permission(tool, perm_level)
    print_success(f"Set {tool} permission to: {perm_level.value}")


@permissions_app.command("reset")
def permissions_reset(force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")):
    """
    Reset all permissions to defaults.
    """
    if not force:
        confirm = typer.confirm("Reset all permissions to defaults?")
        if not confirm:
            print_warning("Cancelled.")
            return

    reset_permissions()
    print_success("Permissions reset to defaults.")


def main():
    app()


if __name__ == "__main__":
    main()
