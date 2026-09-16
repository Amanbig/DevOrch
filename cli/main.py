import os
import time
from pathlib import Path

import questionary
import typer
from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.panel import Panel
from rich.table import Table

from cli.commands._shared import (  # noqa: E402
    SYSTEM_PROMPT,  # noqa: E402, F401 (used by start_repl via SimplePlanner)
    SimplePlanner,
    console,
    create_provider,
)
from cli.commands.ask import ask  # noqa: E402
from cli.commands.edit import edit  # noqa: E402
from cli.commands.run import run  # noqa: E402

# Custom style for questionary prompts
from cli.constants import (  # noqa: E402
    PROMPT_STYLE,
    QUESTIONARY_STYLE,
    SLASH_COMMANDS,
    SlashCommandCompleter,
    print_banner,
)
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
from core.project_context import ProjectContextLoader
from core.project_memory import ProjectMemoryManager
from core.sessions import DEFAULT_MESSAGE_LIMIT, SessionManager
from core.skills import SkillManager
from core.tasks import get_task_manager, reset_task_manager
from providers import PROVIDER_ENV_VARS, PROVIDER_INFO, PROVIDERS, get_provider
from providers.base import ModelInfo
from tools.agent import AgentTool  # noqa: E402
from tools.edit import EditTool
from tools.filesystem import FilesystemTool
from tools.grep import GrepTool
from tools.search import SearchTool
from tools.shell import ShellTool
from tools.task import TaskTool
from tools.terminal_session import TerminalSessionTool
from tools.websearch import WebFetchTool, WebSearchTool
from utils.logger import (
    print_error,
    print_info,
    print_panel,
    print_response,
    print_success,
    print_warning,
)


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
    page_size: int = 15,
) -> str | None:
    """Interactive model selection with 15-per-page pagination and search support.

    Shows 10-15 models per page to keep terminal display clean, with
    Next/Previous page navigation and search across all available models.
    """
    if not models:
        print_warning("No models available.")
        return None

    # For small lists (<= page_size), show directly without pagination
    if len(models) <= page_size:
        max_name = max(len(m.id) for m in models)
        max_name = min(max_name + 2, 45)
        choices = [
            _format_model_choice(m, current_model, i + 1, max_name) for i, m in enumerate(models)
        ]
        try:
            console.print(
                "\n[dim cyan]💡 Tip: Start typing anytime to search/filter models live | ↑↓ navigate | Enter select[/dim cyan]"
            )
            return questionary.select(
                prompt_text or f"Select model for {provider_name}:",
                choices=choices,
                style=QUESTIONARY_STYLE,
                use_search_filter=True,
                use_jk_keys=False,
                instruction="(Type to search live, ↑↓ navigate, Enter to select, Ctrl+C to cancel)",
            ).ask()
        except (KeyboardInterrupt, EOFError):
            return None

    # Multi-page mode for lists larger than page_size
    max_name = max(len(m.id) for m in models)
    max_name = min(max_name + 2, 45)
    total_models = len(models)
    total_pages = (total_models + page_size - 1) // page_size
    current_page = 0

    while True:
        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, total_models)
        page_models = models[start_idx:end_idx]

        page_choices = []

        # Previous page navigation if not on the first page
        if current_page > 0:
            prev_start = (current_page - 1) * page_size + 1
            prev_end = current_page * page_size
            page_choices.append(
                questionary.Choice(
                    f"  ◀  Previous Page ({prev_start}–{prev_end} of {total_models})",
                    value="__prev__",
                )
            )
            page_choices.append(questionary.Separator("─" * 40))

        # Current page model choices
        for i, m in enumerate(page_models):
            global_idx = start_idx + i + 1
            page_choices.append(_format_model_choice(m, current_model, global_idx, max_name))

        # Bottom navigation controls
        nav_choices = []
        if current_page < total_pages - 1:
            next_start = end_idx + 1
            next_end = min(end_idx + page_size, total_models)
            nav_choices.append(
                questionary.Choice(
                    f"  ▶  Next Page ({next_start}–{next_end} of {total_models})",
                    value="__next__",
                )
            )

        nav_choices.append(
            questionary.Choice(
                f"  🔍 Search all {total_models} models...",
                value="__search__",
            )
        )

        page_choices.append(questionary.Separator("─" * 40))
        page_choices.extend(nav_choices)

        base_prompt = prompt_text or f"Select model for {provider_name}"
        page_prompt = f"{base_prompt} [Page {current_page + 1}/{total_pages} ({start_idx + 1}-{end_idx} of {total_models})]:"

        try:
            console.print(
                f"\n[dim cyan]💡 Tip: Showing {len(page_models)} models (Page {current_page + 1}/{total_pages}) | Select Next/Prev to browse | Or choose Search[/dim cyan]"
            )
            selected = questionary.select(
                page_prompt,
                choices=page_choices,
                style=QUESTIONARY_STYLE,
                use_search_filter=True,
                use_jk_keys=False,
                instruction="(Type to filter page, ↑↓ navigate, Enter select, Ctrl+C cancel)",
            ).ask()

            if selected is None:
                return None
            elif selected == "__next__":
                current_page += 1
                continue
            elif selected == "__prev__":
                current_page -= 1
                continue
            elif selected == "__search__":
                query = questionary.text(
                    f"Search {provider_name} models (or press Enter to cancel):",
                    style=QUESTIONARY_STYLE,
                ).ask()
                if not query or not query.strip():
                    continue
                q = query.strip().lower()
                matched = [
                    m for m in models if q in m.id.lower() or (m.name and q in m.name.lower())
                ]
                if not matched:
                    console.print(f"[yellow]No models found matching '{query}'.[/yellow]")
                    continue
                console.print(f"[green]Found {len(matched)} matching models for '{query}':[/green]")
                res = _interactive_model_select(
                    matched,
                    provider_name,
                    current_model=current_model,
                    prompt_text=f"Select from matches for '{query}':",
                    page_size=page_size,
                )
                if res:
                    return res
                continue
            else:
                return selected
        except (KeyboardInterrupt, EOFError):
            return None


def _interactive_provider_select(
    current_provider: str,
    current_settings: "Settings",
    prompt_text: str = "Select provider:",
    allowed_providers: list[str] | None = None,
) -> str | None:
    """Interactive provider selection with status indicators and search filter."""
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
        if allowed_providers and name not in allowed_providers:
            continue
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

    separator = [questionary.Separator("── Local ──")] if (cloud_choices and local_choices) else []
    provider_choices = cloud_choices + separator + local_choices

    try:
        console.print(
            "\n[dim cyan]💡 Tip: Start typing anytime to search/filter providers live | ↑↓ navigate | Enter select[/dim cyan]"
        )
        return questionary.select(
            prompt_text,
            choices=provider_choices,
            style=QUESTIONARY_STYLE,
            use_search_filter=True,
            use_jk_keys=False,
            instruction="(Type to search live, ↑↓ navigate, Enter to select, Ctrl+C to cancel)",
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


# Main app with invoke_without_command=True so we can handle bare `devorch`
app = typer.Typer(
    help=(
        "DevOrch - AI Coding Assistant CLI\n\n"
        "Interactive REPL:  run 'devorch' or 'devorch chat'\n"
        "Non-interactive:   run 'devorch ask', 'devorch edit', 'devorch run', "
        "'devorch models', 'devorch memory', etc."
    ),
    invoke_without_command=True,
    no_args_is_help=False,
)
sessions_app = typer.Typer(help="Manage chat sessions")
app.add_typer(sessions_app, name="sessions")

permissions_app = typer.Typer(help="Manage tool permissions")
app.add_typer(permissions_app, name="permissions")

# Register commands defined in cli/commands/
app.command()(ask)
app.command()(run)
app.command()(edit)


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


def _get_git_branch(cwd: str | None = None) -> str | None:
    """Get current git branch name if cwd is inside a git repository."""
    try:
        import subprocess

        res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd or os.getcwd(),
            capture_output=True,
            text=True,
            timeout=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        if res.returncode == 0:
            branch = res.stdout.strip()
            if branch and branch != "HEAD":
                return branch
    except Exception:
        pass
    return None


def _copy_to_clipboard(text: str) -> bool:
    """Copy text to clipboard using platform-native utilities without extra dependencies."""
    import platform
    import subprocess

    sys_name = platform.system().lower()
    try:
        if sys_name == "windows":
            subprocess.run(
                ["clip"],
                input=text.encode("utf-8"),
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        elif sys_name == "darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
            return True
        else:
            for cmd in [
                ["wl-copy"],
                ["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"],
            ]:
                try:
                    subprocess.run(cmd, input=text.encode("utf-8"), check=True)
                    return True
                except FileNotFoundError:
                    continue
    except Exception:
        pass
    return False


def _create_prompt_keybindings() -> KeyBindings:
    """Create prompt keybindings supporting Alt+Enter for multiline newline insertion."""
    kb = KeyBindings()

    @kb.add("escape", "enter")
    def _(event):
        event.current_buffer.insert_text("\n")

    return kb


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

    # Load project context (DEVORCH.md, CLAUDE.md, etc.)
    project_loader = ProjectContextLoader()
    project_ctx = project_loader.load(os.getcwd())
    project_prompt = project_ctx.to_system_prompt_block() if project_ctx else ""

    # Load persistent per-project memory (cross-session recall)
    project_memory_manager = ProjectMemoryManager(os.getcwd())
    project_memory_prompt = project_memory_manager.to_prompt_context()

    # Create mode manager (shared between agent and executor)
    mode_manager = ModeManager(default_mode=AgentMode.ASK)

    executor = ToolExecutor(tools=tools, require_confirmation=True, mode_manager=mode_manager)
    planner = SimplePlanner(
        memory_context=memory_context,
        project_context=project_prompt,
        project_memory_context=project_memory_prompt,
        tools=tools,
    )

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

    # Inject AgentTool (needs provider + full tool list, so injected after construction)
    agent_tool = AgentTool(provider=llm, tools=tools)
    executor.tools[agent_tool.name] = agent_tool
    agent.tools.append(agent_tool)
    planner.update_tools(agent.tools)

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
    if project_ctx:
        extra_parts.append(
            f"[dim]{project_ctx.file_name} ({project_ctx.estimated_tokens:,} tok)[/dim]"
        )
    if project_memory_prompt:
        dec_count = len(project_memory_manager.memory.decisions)
        sess_count = len(project_memory_manager.memory.recent_sessions)
        mem_info = []
        if dec_count:
            mem_info.append(f"{dec_count} decisions")
        if sess_count:
            mem_info.append(f"{sess_count} sessions")
        desc = ", ".join(mem_info) if mem_info else "active"
        extra_parts.append(f"[dim]memory ({desc})[/dim]")
    elif mem_count:
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
    last_response_text: str = ""
    prompt_kb = _create_prompt_keybindings()

    def get_bottom_toolbar():
        """Clean bottom status bar with git branch, model, mode, and tokens."""
        mode_char = {"plan": "PLAN", "auto": "AUTO", "ask": "ASK"}.get(mode_manager.mode.value, "?")
        tok_count = agent.context_manager.stats.total_tokens
        tok_str = f"⚡ {tok_count:,} tok" if tok_count else "⚡ 0 tok"
        git_b = _get_git_branch()
        parts = [cwd_display]
        if git_b:
            parts.append(f"git:{git_b}")
        parts.extend([f"{current_llm.name}/{current_llm.model}", f"[{mode_char}]", tok_str])
        mcp_n = len(mcp_manager.servers)
        if mcp_n:
            parts.append(f"MCP: {mcp_n}")
        return "  " + "     ".join(parts)

    history_file = Path.home() / ".devorch" / "history"
    history_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_history = FileHistory(str(history_file))

    while True:
        try:
            # Print a clean separator line above the prompt
            rule_width = max(console.width - 1, 10)
            console.print("[dim]─[/dim]" * rule_width, highlight=False)

            # Use prompt_toolkit with autocomplete, mode badge, and bottom toolbar
            mode_tag = mode_manager.mode.value.upper()
            user_input = pt_prompt(
                [
                    ("class:prompt-mode", f"[{mode_tag}] "),
                    ("class:prompt-arrow", "> "),
                ],
                completer=completer,
                complete_while_typing=True,
                style=PROMPT_STYLE,
                bottom_toolbar=get_bottom_toolbar,
                history=prompt_history,
                key_bindings=prompt_kb,
            )

            if user_input.lower() in ("exit", "quit", "q"):
                mcp_manager.stop_all()
                if agent.history and session_manager.current_session_id:
                    project_memory_manager.update_from_session(
                        session_manager.current_session_id, agent.history
                    )
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
                        "Session & Utilities": [
                            "/session",
                            "/history",
                            "/tokens",
                            "/copy",
                            "/paste",
                            "/undo",
                            "/clear",
                            "/compact",
                            "/save",
                        ],
                        "Memory": ["/memory", "/remember", "/forget"],
                        "Skills": ["/skills", "/skill"],
                        "Tools & Config": [
                            "/init",
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
                        "\n[dim]  Tips:\n"
                        "  • Type / for command autocomplete\n"
                        "  • /models and /providers support interactive search and 15-per-page pagination\n"
                        "  • /memory add <decision> records conventions into persistent project memory\n"
                        "  • /tokens shows prompt vs completion tokens, compaction savings, and costs[/dim]\n"
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

                elif cmd in ("clear", "new"):
                    if agent.history and session_manager.current_session_id:
                        project_memory_manager.update_from_session(
                            session_manager.current_session_id, agent.history
                        )
                    agent.history = []
                    planner.project_memory_context = project_memory_manager.to_prompt_context()
                    print_success("Conversation cleared (project memory preserved).")
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

                elif cmd == "tokens":
                    stats = agent.context_manager.stats
                    console.print()
                    table = Table(title="Token Usage & Session Statistics", border_style="cyan")
                    table.add_column("Metric", style="bold white")
                    table.add_column("Value", style="cyan")

                    table.add_row("Total Turns", f"{stats.total_turns:,}")
                    table.add_row("Prompt Tokens", f"{stats.prompt_tokens:,}")
                    table.add_row("Completion Tokens", f"{stats.completion_tokens:,}")
                    table.add_row("Cached Tokens", f"{stats.cached_tokens:,}")
                    table.add_row("Total Tokens", f"[bold]{stats.total_tokens:,}[/bold]")
                    table.add_row("History Compactions", f"{stats.history_compactions:,}")

                    if agent.last_turn_usage:
                        table.add_row(
                            "Last Turn",
                            f"{agent.last_turn_usage.total_tokens:,} tok ({agent.last_turn_usage.prompt_tokens:,} prompt, {agent.last_turn_usage.completion_tokens:,} comp)",
                        )

                    console.print(table)
                    console.print()
                    continue

                elif cmd == "init":
                    try:
                        target = ProjectContextLoader.init_project_file(
                            directory=os.getcwd(), overwrite=False
                        )
                        print_success(f"Initialized {target.name} successfully!")
                        pctx = project_loader.load(os.getcwd(), force_reload=True)
                        if pctx:
                            planner.project_context = pctx.to_system_prompt_block()
                            print_info(
                                f"Loaded {pctx.file_name} into active session guidelines ({pctx.estimated_tokens:,} tokens)."
                            )
                    except FileExistsError:
                        print_warning("DEVORCH.md already exists in this directory.")
                    except Exception as e:
                        print_error(f"Failed to initialize DEVORCH.md: {e}")
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
                        arg_lower = cmd_arg.lower().strip()
                        if arg_lower in PROVIDERS:
                            new_provider = arg_lower
                        else:
                            # Check prefix / substring matches across provider keys
                            matches = [p for p in PROVIDERS if arg_lower in p.lower()]
                            if len(matches) == 1:
                                new_provider = matches[0]
                                print_info(f"Matched provider: {new_provider}")
                            elif len(matches) > 1:
                                console.print(
                                    f"\n[yellow]Multiple matches for '{cmd_arg}':[/yellow]"
                                )
                                new_provider = _interactive_provider_select(
                                    current_llm.name,
                                    current_settings,
                                    prompt_text="Select provider from matches:",
                                    allowed_providers=matches,
                                )
                                if not new_provider:
                                    continue
                            else:
                                print_error(
                                    f"Unknown provider '{cmd_arg}'. Available: {', '.join(PROVIDERS.keys())}"
                                )
                                continue
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
                    pm = project_memory_manager.memory
                    console.print(
                        f"\n[bold]🧠 Project Memory: [cyan]{pm.project_name}[/cyan][/bold]"
                    )
                    console.print(f"  [dim]Storage:[/dim] {project_memory_manager.memory_file}")
                    if pm.tech_stack:
                        console.print(f"  [dim]Tech Stack:[/dim] {', '.join(pm.tech_stack)}")

                    if cmd_arg:
                        arg_parts = cmd_arg.split(maxsplit=1)
                        sub_cmd = arg_parts[0].lower()
                        sub_val = arg_parts[1] if len(arg_parts) > 1 else ""

                        if sub_cmd == "add" and sub_val:
                            project_memory_manager.add_decision(sub_val)
                            planner.project_memory_context = (
                                project_memory_manager.to_prompt_context()
                            )
                            print_success(f"Added to project memory: {sub_val}")
                            continue
                        elif sub_cmd == "pref" and sub_val:
                            project_memory_manager.add_preference(sub_val)
                            planner.project_memory_context = (
                                project_memory_manager.to_prompt_context()
                            )
                            print_success(f"Saved user preference: {sub_val}")
                            continue
                        elif sub_cmd == "clear":
                            project_memory_manager.clear()
                            planner.project_memory_context = ""
                            print_success("Project memory cleared.")
                            continue

                    if pm.decisions:
                        console.print(
                            "\n  [bold cyan]Architectural Decisions & Conventions:[/bold cyan]"
                        )
                        for d in pm.decisions:
                            console.print(f"    - {d}")

                    if pm.preferences:
                        console.print("\n  [bold yellow]User Preferences:[/bold yellow]")
                        for p in pm.preferences:
                            console.print(f"    - {p}")

                    if pm.recent_sessions:
                        console.print(
                            "\n  [bold green]Recent Sessions (Accomplishments):[/bold green]"
                        )
                        for s in pm.recent_sessions:
                            console.print(f"    - [{s.get('date', '')}] {s.get('summary', '')}")

                    if not (pm.decisions or pm.preferences or pm.recent_sessions):
                        console.print(
                            "\n  [dim]No project memories recorded yet. DevOrch records accomplishments automatically when sessions end.[/dim]"
                        )

                    # Show global memories count if any exist
                    global_mems = memory_manager.list_all()
                    if global_mems:
                        console.print(
                            f"\n  [dim]Global Memories: {len(global_mems)} item(s) in ~/.devorch/memory/[/dim]"
                        )

                    console.print(
                        "\n[dim]  Commands: /memory add <decision> | /memory pref <pref> | /memory clear[/dim]\n"
                    )
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
                    # Sub-command dispatch: /mcp [add|stop|start] [args...]
                    mcp_parts = cmd_arg.split() if cmd_arg else []
                    mcp_sub = mcp_parts[0] if mcp_parts else None

                    if mcp_sub == "add":
                        # /mcp add <name> <command> [arg1 arg2 ...]
                        if len(mcp_parts) < 3:
                            print_warning("Usage: /mcp add <name> <command> [args...]")
                            print_info(
                                "Example: /mcp add github npx -y @modelcontextprotocol/server-github"
                            )
                        else:
                            mcp_name = mcp_parts[1]
                            mcp_cmd = mcp_parts[2]
                            mcp_cmd_args = mcp_parts[3:]
                            with console.status(
                                f"[bold cyan]Starting '{mcp_name}'...", spinner="dots"
                            ):
                                ok, new_tools = mcp_manager.add_server(
                                    mcp_name, mcp_cmd, mcp_cmd_args
                                )
                            if ok:
                                for t in new_tools:
                                    executor.tools[t.name] = t
                                    agent.tools.append(t)
                                planner.update_tools(agent.tools)
                                print_success(
                                    f"'{mcp_name}' connected — {len(new_tools)} tool(s) added"
                                )
                                if new_tools:
                                    console.print(
                                        f"  [dim]Tools: {', '.join(t.name for t in new_tools)}[/dim]"
                                    )
                            else:
                                print_error(f"Failed to start MCP server '{mcp_name}'")

                    elif mcp_sub == "stop":
                        # /mcp stop <name>
                        if len(mcp_parts) < 2:
                            print_warning("Usage: /mcp stop <name>")
                        else:
                            mcp_name = mcp_parts[1]
                            if mcp_manager.stop_server(mcp_name):
                                prefix = f"mcp_{mcp_name}_"
                                removed = [k for k in list(executor.tools) if k.startswith(prefix)]
                                for k in removed:
                                    del executor.tools[k]
                                agent.tools = [
                                    t for t in agent.tools if not t.name.startswith(prefix)
                                ]
                                planner.update_tools(agent.tools)
                                print_success(
                                    f"'{mcp_name}' stopped — {len(removed)} tool(s) removed"
                                )
                            else:
                                print_error(f"No server named '{mcp_name}' is connected")

                    elif mcp_sub == "start":
                        # /mcp start <name> — reconnect from config
                        if len(mcp_parts) < 2:
                            print_warning("Usage: /mcp start <name>")
                        else:
                            mcp_name = mcp_parts[1]
                            mcp_cfg = (settings.mcp_servers or {}).get(mcp_name)
                            if not mcp_cfg:
                                print_error(
                                    f"'{mcp_name}' not found in config. "
                                    "Use /mcp add <name> <command> [args...] to connect a new server."
                                )
                            else:
                                with console.status(
                                    f"[bold cyan]Starting '{mcp_name}'...", spinner="dots"
                                ):
                                    ok, new_tools = mcp_manager.add_server(
                                        mcp_name,
                                        mcp_cfg.get("command", ""),
                                        mcp_cfg.get("args", []),
                                        mcp_cfg.get("env", {}),
                                        mcp_cfg.get("cwd"),
                                    )
                                if ok:
                                    for t in new_tools:
                                        executor.tools[t.name] = t
                                        agent.tools.append(t)
                                    planner.update_tools(agent.tools)
                                    print_success(
                                        f"'{mcp_name}' started — {len(new_tools)} tool(s) added"
                                    )
                                else:
                                    print_error(f"Failed to start MCP server '{mcp_name}'")

                    else:
                        # /mcp — show status
                        servers = mcp_manager.list_servers()
                        if not servers:
                            console.print("\n[bold]MCP Servers:[/bold] None connected")
                            console.print(
                                "[dim]Configure in ~/.devorch/config.yaml, or connect inline:[/dim]"
                            )
                            console.print(
                                "[dim]  /mcp add <name> <command> [args...]  — connect a new server[/dim]\n"
                                "[dim]  /mcp start <name>                    — reconnect from config[/dim]\n"
                                "[dim]  /mcp stop <name>                     — disconnect a server[/dim]\n"
                            )
                        else:
                            console.print(f"\n[bold]MCP Servers ({len(servers)}):[/bold]")
                            for srv in servers:
                                status = (
                                    "[green]running[/green]"
                                    if srv["running"]
                                    else "[red]stopped[/red]"
                                )
                                console.print(f"  [cyan]{srv['name']}[/cyan] — {status}")
                                if srv["tools"]:
                                    console.print(f"    Tools: {', '.join(srv['tools'])}")
                            console.print(
                                "\n[dim]/mcp add <name> <cmd> [args]  "
                                "| /mcp stop <name>  "
                                "| /mcp start <name>[/dim]"
                            )
                    console.print()
                    continue

                # Also handle direct skill invocation (e.g. /commit, /review)
                elif cmd in [s["name"] for s in skill_manager.list_skills()]:
                    skill = skill_manager.get(cmd)
                    if skill:
                        console.print(
                            f"  [dim]Running skill:[/dim] [cyan]{cmd}[/cyan] - {skill['description']}"
                        )
                        t0 = time.time()
                        result = agent.run(skill["prompt"], max_iterations=15)
                        elapsed = time.time() - t0
                        last_response_text = result
                        print_response(result)
                        if agent.last_turn_usage and agent.last_turn_usage.total_tokens:
                            u = agent.last_turn_usage
                            tok_sec = (
                                f" | {elapsed:.1f}s ({int(u.completion_tokens / elapsed)} tok/s)"
                                if elapsed > 0.1 and u.completion_tokens
                                else f" | {elapsed:.1f}s"
                            )
                            console.print(
                                f"  [dim]⚡ {u.total_tokens:,} tokens ({u.prompt_tokens:,} prompt, {u.completion_tokens:,} comp){tok_sec} | "
                                f"Session: {agent.context_manager.stats.total_tokens:,} tok[/dim]\n"
                            )
                        continue

                elif cmd == "copy":
                    if not last_response_text:
                        print_warning("No assistant response to copy yet.")
                    elif _copy_to_clipboard(last_response_text):
                        print_success("Copied last response to clipboard.")
                    else:
                        print_warning("Clipboard utility not available on this system.")
                    continue

                elif cmd == "paste":
                    console.print(
                        "[cyan]Multi-line paste mode:[/cyan] Paste or type your text below. "
                        "Type [bold]END[/bold] on an empty line or press [bold]Ctrl+D[/bold] to submit:\n"
                    )
                    lines = []
                    try:
                        while True:
                            line = input()
                            if line.strip() == "END":
                                break
                            lines.append(line)
                    except (EOFError, KeyboardInterrupt):
                        pass
                    pasted_input = "\n".join(lines).strip()
                    if not pasted_input:
                        print_info("Paste cancelled.")
                        continue
                    console.print(f"[dim]Processing {len(lines)} pasted line(s)...[/dim]")
                    user_input = pasted_input

                else:
                    print_warning(f"Unknown command: /{cmd}")
                    print_info("Type /help to see available commands")
                    continue

            t0 = time.time()
            result = agent.run(user_input, max_iterations=15)
            elapsed = time.time() - t0
            last_response_text = result
            print_response(result)
            if agent.last_turn_usage and agent.last_turn_usage.total_tokens:
                u = agent.last_turn_usage
                tok_sec = (
                    f" | {elapsed:.1f}s ({int(u.completion_tokens / elapsed)} tok/s)"
                    if elapsed > 0.1 and u.completion_tokens
                    else f" | {elapsed:.1f}s"
                )
                console.print(
                    f"  [dim]⚡ {u.total_tokens:,} tokens ({u.prompt_tokens:,} prompt, {u.completion_tokens:,} comp){tok_sec} | "
                    f"Session: {agent.context_manager.stats.total_tokens:,} tok[/dim]\n"
                )

        except (typer.Abort, EOFError):
            mcp_manager.stop_all()
            if agent.history and session_manager.current_session_id:
                project_memory_manager.update_from_session(
                    session_manager.current_session_id, agent.history
                )
            print_info(f"\nSession saved: {session_manager.current_session_id}")
            break
        except KeyboardInterrupt:
            mcp_manager.stop_all()
            if agent.history and session_manager.current_session_id:
                project_memory_manager.update_from_session(
                    session_manager.current_session_id, agent.history
                )
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
    List available AI providers and their configuration status (non-interactive).
    """
    settings = Settings.load()
    table = Table(title="DevOrch AI Providers")
    table.add_column("Provider", style="cyan bold")
    table.add_column("Description", style="white")
    table.add_column("Status", style="green")
    table.add_column("Default Model", style="blue")

    for name in PROVIDERS.keys():
        desc = PROVIDER_INFO.get(name, "")
        short_desc = desc.split(" - ", 1)[1] if " - " in desc else desc
        cfg = settings.providers.get(name)
        if name in ("local", "lmstudio"):
            status = "[cyan]Local (no key)[/cyan]"
        elif cfg and cfg.api_key:
            status = "[green]Configured[/green]"
        else:
            status = "[dim]Not configured[/dim]"

        if name == settings.default_provider:
            status += " [bold yellow](default)[/bold yellow]"

        default_model = cfg.default_model if cfg and cfg.default_model else "-"
        table.add_row(name, short_desc, status, default_model)

    console.print(table)
    console.print(
        "\n[dim]Set API key: devorch set-key <provider> | In REPL: /providers or /provider <name>[/dim]"
    )


@app.command("models")
def models_list(
    provider: str = typer.Argument(
        None,
        help="Provider name (e.g. openai, anthropic, gemini, groq). Defaults to active provider.",
    ),
):
    """
    List available models for a provider (non-interactive).
    """
    settings = Settings.load()
    target_provider = (provider or settings.default_provider or "openai").lower()

    if target_provider not in PROVIDERS:
        print_error(
            f"Unknown provider '{target_provider}'. Available: {', '.join(PROVIDERS.keys())}"
        )
        raise typer.Exit(1)

    api_key = settings.get_api_key(target_provider)
    try:
        temp_provider = get_provider(target_provider, api_key=api_key or "placeholder")
        models = temp_provider.list_models()
    except Exception as e:
        print_error(f"Could not list models for {target_provider}: {e}")
        raise typer.Exit(1) from e

    if not models:
        print_warning(f"No models returned for {target_provider}.")
        return

    table = Table(title=f"Models for {target_provider.title()}")
    table.add_column("Model ID", style="cyan bold")
    table.add_column("Description", style="white")
    table.add_column("Context Window", style="green")

    cfg = settings.providers.get(target_provider)
    configured_model = cfg.default_model if cfg else ""

    for m in models:
        is_cur = " [bold yellow](current)[/bold yellow]" if m.id == configured_model else ""
        ctx = f"{m.context_length:,} tok" if m.context_length else "-"
        table.add_row(f"{m.id}{is_cur}", m.description or "-", ctx)

    console.print(table)
    console.print(
        f"\n[dim]Use model: devorch -p {target_provider} -m <model_id> | In REPL: /models or /model <id>[/dim]"
    )


@app.command("memory")
def memory_cmd(
    action: str = typer.Argument(
        "show",
        help="Action: show (default), clear, add (record decision), or pref (record preference)",
    ),
    text: str = typer.Argument(None, help="Text to add (required if action is 'add' or 'pref')"),
):
    """
    View or manage persistent project memory (decisions & conventions) non-interactively.
    """
    mgr = ProjectMemoryManager(os.getcwd())

    if action == "clear":
        mgr.clear()
        print_success("Project memory cleared for this directory.")
        return

    if action in ("add", "decision"):
        if not text:
            print_error("Please specify the decision text: devorch memory add <text>")
            raise typer.Exit(1)
        mgr.add_decision(text)
        print_success(f"Added architectural decision: {text}")
        return

    if action in ("pref", "preference"):
        if not text:
            print_error("Please specify the preference text: devorch memory pref <text>")
            raise typer.Exit(1)
        mgr.add_user_preference(text)
        print_success(f"Added user preference: {text}")
        return

    # Default action: show
    pm = mgr.memory
    console.print(
        f"\n[bold cyan]DevOrch Project Memory[/bold cyan] [dim]({mgr.memory_file})[/dim]\n"
    )

    if pm.decisions:
        console.print("  [bold cyan]Architectural Decisions & Conventions:[/bold cyan]")
        for d in pm.decisions:
            console.print(f"    - {d}")

    if pm.preferences:
        console.print("\n  [bold yellow]User Preferences:[/bold yellow]")
        for p in pm.preferences:
            console.print(f"    - {p}")

    if pm.recent_sessions:
        console.print("\n  [bold green]Recent Sessions (Accomplishments):[/bold green]")
        for s in pm.recent_sessions:
            console.print(f"    - [{s.get('date', '')}] {s.get('summary', '')}")

    if not (pm.decisions or pm.preferences or pm.recent_sessions):
        console.print("  [dim]No project memories recorded yet for this directory.[/dim]")

    console.print(
        "\n[dim]Commands: devorch memory add <decision> | devorch memory pref <pref> | devorch memory clear[/dim]"
    )


@app.command("skills")
def skills_list():
    """
    List all available skills.
    """
    skill_manager = SkillManager()
    all_skills = skill_manager.list_skills()

    if not all_skills:
        print_info("No skills found.")
        return

    table = Table(title="Available Skills")
    table.add_column("Name", style="cyan")
    table.add_column("Description", style="white")
    table.add_column("Source", style="dim")

    for s in all_skills:
        table.add_row(s["name"], s["description"], s.get("source", "built-in"))

    console.print(table)
    console.print("\n[dim]Run a skill: devorch ask --skill <name>[/dim]")


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


@app.command(name="init")
def init_project(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing DEVORCH.md"),
):
    """
    Initialize a DEVORCH.md project context file in the current directory.
    """
    try:
        target = ProjectContextLoader.init_project_file(directory=os.getcwd(), overwrite=force)
        print_success(f"Initialized {target.name} successfully!")
        console.print(f"  [dim]Project instructions generated at {target}[/dim]")
    except FileExistsError:
        print_warning("DEVORCH.md already exists in this directory. Use --force to overwrite.")
    except Exception as e:
        print_error(f"Failed to initialize: {e}")


def main():
    app()


if __name__ == "__main__":
    main()
