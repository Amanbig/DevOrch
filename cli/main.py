import typer
from typing import List, Optional, Dict, Callable, Any
from rich.table import Table
import os

from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style

from core.agent import Agent
from core.executor import ToolExecutor
from core.sessions import SessionManager, DEFAULT_MESSAGE_LIMIT
from core.modes import ModeManager, AgentMode
from providers import get_provider, PROVIDERS
from config.settings import Settings, set_api_key, keyring_available, save_config
from config.permissions import get_permissions, reset_permissions, PermissionLevel, PERMISSIONS_FILE
from utils.logger import get_console, print_error, print_success, print_panel, print_warning, print_info

from tools.shell import ShellTool
from tools.filesystem import FilesystemTool
from tools.search import SearchTool
from tools.grep import GrepTool
from tools.edit import EditTool

from core.planner import Planner
from schemas.message import Message


# ASCII Art Banner
BANNER = r"""
[bold blue]
 ____             ____  _ _       _
|  _ \  _____   _|  _ \(_) | ___ | |_
| | | |/ _ \ \ / / |_) | | |/ _ \| __|
| |_| |  __/\ V /|  __/| | | (_) | |_
|____/ \___| \_/ |_|   |_|_|\___/ \__|
[/bold blue]
"""

BANNER_SMALL = "[bold blue]DevPilot[/bold blue] - AI Coding Assistant"

VERSION = "0.1.0"

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
    "/model": "Switch to a different model",
    "/provider": "Switch to a different provider",
    "/history": "Show conversation history",
    "/undo": "Undo last message",
    "/save": "Save conversation to file",
}

# Style for prompt_toolkit
PROMPT_STYLE = Style.from_dict({
    "prompt": "#00aa00 bold",
    "command": "#0088ff",
    "description": "#888888",
})


class SlashCommandCompleter(Completer):
    """Autocomplete for slash commands."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Only complete if starts with /
        if not text.startswith("/"):
            return

        # Get the partial command
        partial = text.lower()

        for cmd, desc in SLASH_COMMANDS.items():
            if cmd.startswith(partial):
                # Calculate how much to complete
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display=HTML(f"<command>{cmd}</command> <description>- {desc}</description>"),
                    display_meta=desc,
                )


def print_banner(small: bool = False):
    """Print the DevPilot banner."""
    if small:
        console.print(BANNER_SMALL)
    else:
        console.print(BANNER)
        console.print(f"  [dim]v{VERSION} - Your AI Coding Assistant[/dim]\n")


class SimplePlanner(Planner):
    def plan(self, history: List[Message]) -> List[Message]:
        system_prompt = Message(
            role="system",
            content="You are DevPilot, an AI coding assistant. You have access to tools to interact with the local machine. Use them to help the user."
        )
        return [system_prompt] + history


# Main app with invoke_without_command=True so we can handle bare `devpilot`
app = typer.Typer(
    help="DevPilot - Your AI Coding Assistant",
    invoke_without_command=True,
    no_args_is_help=False
)
sessions_app = typer.Typer(help="Manage chat sessions")
app.add_typer(sessions_app, name="sessions")

permissions_app = typer.Typer(help="Manage tool permissions")
app.add_typer(permissions_app, name="permissions")

console = get_console()


def has_any_api_key(settings: Settings) -> bool:
    """Check if any provider has an API key configured."""
    for name in ["openai", "anthropic", "gemini"]:
        if settings.get_api_key(name):
            return True
    return False


def run_onboarding() -> Optional[str]:
    """Run first-time setup. Returns the configured provider name or None."""
    print_banner()
    console.print("[bold]First time setup[/bold] - Let's configure your AI provider.\n")

    # Show available providers
    console.print("[bold]Available providers:[/bold]")
    console.print("  1. [cyan]openai[/cyan]     - GPT-4o, GPT-4, etc.")
    console.print("  2. [cyan]anthropic[/cyan]  - Claude Sonnet, Opus, etc.")
    console.print("  3. [cyan]gemini[/cyan]     - Gemini Pro, Flash, etc.")
    console.print("  4. [cyan]local[/cyan]      - Ollama (no API key needed)")
    console.print()

    # Ask which provider to set up
    choice = typer.prompt(
        "Which provider would you like to use? (1-4 or name)",
        default="1"
    )

    provider_map = {
        "1": "openai", "2": "anthropic", "3": "gemini", "4": "local",
        "openai": "openai", "anthropic": "anthropic", "gemini": "gemini", "local": "local"
    }

    provider = provider_map.get(choice.lower().strip())
    if not provider:
        print_error(f"Unknown provider: {choice}")
        return None

    if provider == "local":
        print_success("Local provider selected - no API key needed!")
        print_info("Make sure Ollama is running at http://localhost:11434")
        return provider

    # Get API key
    env_vars = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GOOGLE_API_KEY"
    }

    console.print(f"\n[bold]Setting up {provider}[/bold]")
    console.print(f"You can also set the [cyan]{env_vars[provider]}[/cyan] environment variable.\n")

    api_key = typer.prompt(f"Enter your {provider} API key", hide_input=True)

    if not api_key.strip():
        print_error("API key cannot be empty.")
        return None

    # Try to store in keyring
    if keyring_available():
        if set_api_key(provider, api_key.strip()):
            print_success(f"API key stored securely in system keychain!")
        else:
            print_warning("Could not store in keychain. Key will only be available this session.")
    else:
        print_warning("Keychain not available. Set the environment variable for persistence.")

    # Save as default provider
    settings = Settings.load()
    settings.default_provider = provider
    settings.providers[provider].api_key = api_key.strip()

    try:
        save_config(settings)
        print_success(f"Default provider set to: {provider}")
    except Exception:
        pass  # Config save failed, but key is in memory

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
        print_error(f"Use 'devpilot set-key {provider_name}' or set {env_var_name} environment variable")
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
    provider: Optional[str] = None,
    model: Optional[str] = None,
    resume: Optional[str] = None,
    message_limit: int = DEFAULT_MESSAGE_LIMIT,
    show_banner: bool = True
):
    """Start the interactive REPL session."""
    if show_banner:
        print_banner()

    settings = Settings.load()
    session_manager = SessionManager(message_limit=message_limit)

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
            raise typer.Exit(1)
    else:
        messages = []

    if not provider:
        provider = settings.default_provider

    llm = create_provider(provider, model, settings)

    # Create new session if not resuming
    if not resume:
        session_id = session_manager.create_session(llm.name, llm.model)

    tools = [ShellTool(), FilesystemTool(), SearchTool(), GrepTool(), EditTool()]

    # Create mode manager (shared between agent and executor)
    mode_manager = ModeManager(default_mode=AgentMode.ASK)

    executor = ToolExecutor(tools=tools, require_confirmation=True, mode_manager=mode_manager)
    planner = SimplePlanner()

    def on_session_continue(new_session_id: str):
        print_info(f"Session continued: {new_session_id}")

    agent = Agent(
        provider=llm,
        planner=planner,
        executor=executor,
        tools=tools,
        session_manager=session_manager,
        on_session_continue=on_session_continue,
        mode_manager=mode_manager
    )

    if messages:
        agent.set_history(messages)

    if context_summary:
        agent.set_context_summary(context_summary)

    # Get current working directory for display
    cwd = os.getcwd()
    cwd_short = os.path.basename(cwd) or cwd

    # Show session info
    console.print(f"  [dim]Provider:[/dim] [cyan]{llm.name}[/cyan]  [dim]Model:[/dim] [cyan]{llm.model}[/cyan]")
    console.print(f"  [dim]Session:[/dim] {session_manager.current_session_id}  [dim]cwd:[/dim] {cwd_short}")
    console.print(f"  [dim]Mode:[/dim] {mode_manager.get_mode_display()}  [dim]- Type[/dim] / [dim]to see commands[/dim]\n")

    # Create completer for slash commands
    completer = SlashCommandCompleter()

    # Track current provider/model for switching
    current_llm = llm
    current_settings = settings

    def get_prompt():
        """Generate prompt with mode indicator."""
        mode_indicator = {
            AgentMode.PLAN: "[yellow]P[/yellow]",
            AgentMode.AUTO: "[green]A[/green]",
            AgentMode.ASK: "[blue]?[/blue]",
        }.get(mode_manager.mode, "")
        return f"[{mode_indicator}] {cwd_short}> "

    while True:
        try:
            # Build prompt with mode indicator
            mode_char = {"plan": "P", "auto": "A", "ask": "?"}.get(mode_manager.mode.value, "?")
            prompt_str = f"[{mode_char}] {cwd_short}> "

            # Use prompt_toolkit with autocomplete
            user_input = pt_prompt(
                prompt_str,
                completer=completer,
                complete_while_typing=True,
                style=PROMPT_STYLE,
            )

            if user_input.lower() in ("exit", "quit", "q"):
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
                    console.print("\n[bold]Available Commands:[/bold]")
                    for slash_cmd, desc in SLASH_COMMANDS.items():
                        console.print(f"  [cyan]{slash_cmd:<14}[/cyan] - {desc}")
                    console.print(f"  [cyan]{'exit':<14}[/cyan] - Exit DevPilot")
                    console.print("\n[bold]Modes:[/bold]")
                    console.print("  [yellow]PLAN[/yellow] - Shows plan before executing, asks for approval")
                    console.print("  [green]AUTO[/green] - Executes tools automatically (trusted mode)")
                    console.print("  [blue]ASK[/blue]  - Asks before each tool execution (default)")
                    console.print("\n[dim]Tip: Type / and use Tab for autocomplete[/dim]\n")
                    continue

                elif cmd == "mode":
                    if cmd_arg:
                        mode_name = cmd_arg.lower()
                        if mode_name in ("plan", "auto", "ask"):
                            mode_manager.mode = AgentMode(mode_name)
                            print_success(f"Switched to {mode_name.upper()} mode")
                            console.print(f"  [dim]{mode_manager.get_mode_description()}[/dim]")
                        else:
                            print_error(f"Unknown mode: {mode_name}")
                            print_info("Available modes: plan, auto, ask")
                    else:
                        console.print(f"\n[bold]Current mode:[/bold] {mode_manager.get_mode_display()}")
                        console.print(f"  {mode_manager.get_mode_description()}")
                        console.print("\n[bold]Available modes:[/bold]")
                        console.print("  [yellow]plan[/yellow] - Shows plan before executing, asks for approval")
                        console.print("  [green]auto[/green] - Executes tools automatically (trusted mode)")
                        console.print("  [blue]ask[/blue]  - Asks before each tool execution (default)")
                        console.print("\n[dim]Usage: /mode <plan|auto|ask>[/dim]\n")
                    continue

                elif cmd == "plan":
                    mode_manager.mode = AgentMode.PLAN
                    print_success("Switched to PLAN mode")
                    console.print("  [dim]I'll show you the plan before executing anything[/dim]")
                    continue

                elif cmd == "auto":
                    mode_manager.mode = AgentMode.AUTO
                    print_success("Switched to AUTO mode")
                    console.print("  [dim]I'll execute tools automatically (dangerous commands still blocked)[/dim]")
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
                    print_info(f"Keyring: {'available' if keyring_available() else 'not available'}")
                    console.print()
                    continue

                elif cmd == "permissions":
                    perms = get_permissions()
                    console.print("\n[bold]Tool Permissions:[/bold]")
                    for tool_name, perm in perms.tools.items():
                        level_color = {"allow": "green", "deny": "red", "ask": "yellow"}.get(perm.level.value, "white")
                        console.print(f"  {tool_name}: [{level_color}]{perm.level.value}[/{level_color}]")
                    if perms.session_allowed:
                        console.print(f"\n[green]Session allowed:[/green] {len(perms.session_allowed)} patterns")
                    console.print()
                    continue

                elif cmd == "compact":
                    print_info("Compacting conversation history...")
                    summary = agent._generate_summary()
                    agent.history = []
                    agent.set_context_summary(summary)
                    print_success("History compacted. Summary preserved.")
                    continue

                elif cmd == "model":
                    if cmd_arg:
                        try:
                            new_llm = get_provider(current_llm.name, model=cmd_arg, api_key=current_settings.get_api_key(current_llm.name))
                            current_llm = new_llm
                            agent.provider = new_llm
                            print_success(f"Switched to model: {cmd_arg}")
                        except Exception as e:
                            print_error(f"Failed to switch model: {e}")
                    else:
                        console.print(f"\n[bold]Current model:[/bold] {current_llm.model}")
                        console.print("[dim]Usage: /model <model-name>[/dim]\n")
                    continue

                elif cmd == "provider":
                    if cmd_arg:
                        new_provider = cmd_arg.lower()
                        if new_provider not in PROVIDERS:
                            print_error(f"Unknown provider: {new_provider}")
                        else:
                            try:
                                new_llm = create_provider(new_provider, None, current_settings)
                                current_llm = new_llm
                                agent.provider = new_llm
                                print_success(f"Switched to provider: {new_provider} ({new_llm.model})")
                            except Exception as e:
                                print_error(f"Failed to switch provider: {e}")
                    else:
                        console.print(f"\n[bold]Current provider:[/bold] {current_llm.name}")
                        console.print(f"[bold]Available:[/bold] {', '.join(PROVIDERS.keys())}")
                        console.print("[dim]Usage: /provider <name>[/dim]\n")
                    continue

                elif cmd == "history":
                    console.print("\n[bold]Conversation History[/bold]")
                    if not agent.history:
                        print_info("No messages yet.")
                    else:
                        for i, msg in enumerate(agent.history[-10:], 1):
                            role_color = {"user": "green", "assistant": "blue", "tool": "yellow"}.get(msg.role, "white")
                            content_preview = (msg.content[:80] + "...") if len(msg.content) > 80 else msg.content
                            console.print(f"  [{role_color}]{msg.role}[/{role_color}]: {content_preview}")
                        if len(agent.history) > 10:
                            console.print(f"  [dim]... and {len(agent.history) - 10} more messages[/dim]")
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
                    filename = cmd_arg or f"devpilot_session_{session_manager.current_session_id}.txt"
                    try:
                        with open(filename, "w") as f:
                            for msg in agent.history:
                                f.write(f"[{msg.role}]\n{msg.content}\n\n")
                        print_success(f"Saved to: {filename}")
                    except Exception as e:
                        print_error(f"Failed to save: {e}")
                    continue

                else:
                    print_warning(f"Unknown command: /{cmd}")
                    print_info("Type /help to see available commands")
                    continue

            result = agent.run(user_input, max_iterations=15)
            print_panel(result, title="DevPilot", border_style="green")

        except (typer.Abort, EOFError):
            print_info(f"\nSession saved: {session_manager.current_session_id}")
            break
        except KeyboardInterrupt:
            console.print()  # New line after ^C
            continue  # Don't exit on Ctrl+C, just cancel current input
        except Exception as e:
            print_error(str(e))


@app.callback()
def main_callback(
    ctx: typer.Context,
    provider: str = typer.Option(None, "--provider", "-p", help="LLM Provider"),
    model: str = typer.Option(None, "--model", "-m", help="Model name"),
    resume: str = typer.Option(None, "--resume", "-r", help="Resume session by ID"),
):
    """
    DevPilot - Your AI Coding Assistant

    Just run 'devpilot' to start chatting!
    """
    # If a subcommand is being invoked, don't run the default behavior
    if ctx.invoked_subcommand is not None:
        return

    # No subcommand - run the default REPL behavior
    settings = Settings.load()

    # Check if we need onboarding
    if not has_any_api_key(settings):
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
    message_limit: int = typer.Option(DEFAULT_MESSAGE_LIMIT, "--limit", "-l", help="Messages before auto-summarization")
):
    """
    Start an interactive chat session (alias for running devpilot directly).
    """
    settings = Settings.load()

    if not has_any_api_key(settings):
        configured_provider = run_onboarding()
        if not configured_provider:
            raise typer.Exit(1)
        settings = Settings.load()
        provider = configured_provider

    start_repl(provider=provider, model=model, resume=resume, message_limit=message_limit)


@app.command()
def ask(
    prompt: str = typer.Argument(..., help="The prompt or question for DevPilot"),
    provider: str = typer.Option(None, "--provider", "-p", help="LLM Provider"),
    model: str = typer.Option(None, "--model", "-m", help="Model name")
):
    """
    Ask DevPilot a single question (non-interactive).
    """
    settings = Settings.load()

    if not provider:
        provider = settings.default_provider

    llm = create_provider(provider, model, settings)

    tools = [ShellTool(), FilesystemTool(), SearchTool(), GrepTool(), EditTool()]
    executor = ToolExecutor(tools=tools)
    planner = SimplePlanner()

    agent = Agent(
        provider=llm,
        planner=planner,
        executor=executor,
        tools=tools
    )

    console.print(f"[dim]Using {llm.name}/{llm.model}[/dim]")
    try:
        result = agent.run(prompt, max_iterations=15)
        print_panel(result, title="DevPilot", border_style="green")
    except Exception as e:
        print_error(str(e))


@app.command()
def config():
    """
    Show current configuration.
    """
    settings = Settings.load()

    console.print("\n[bold]DevPilot Configuration[/bold]\n")
    console.print(f"Default Provider: [cyan]{settings.default_provider}[/cyan]")
    console.print(f"Keyring Available: {'[green]yes[/green]' if keyring_available() else '[yellow]no[/yellow]'}")
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
    provider: str = typer.Argument(..., help="Provider name (openai, anthropic, gemini)")
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
    limit: int = typer.Option(20, "--limit", "-n", help="Number of sessions to show")
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
            session["updated_at"][:16]
        )

    console.print(table)


@sessions_app.command("show")
def sessions_show(
    session_id: str = typer.Argument(..., help="Session ID to show details")
):
    """
    Show details of a specific session.
    """
    session_manager = SessionManager()

    try:
        session_info, messages = session_manager.load_session(session_id)
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)

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
def sessions_delete(
    session_id: str = typer.Argument(..., help="Session ID to delete")
):
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
def sessions_clear(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")
):
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
            PermissionLevel.ASK: "yellow"
        }.get(perm.level, "white")

        console.print(f"[bold]{tool_name}[/bold]: [{level_color}]{perm.level.value}[/{level_color}]")

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
    pattern: str = typer.Argument(..., help="Command pattern to allow (e.g., 'git *')")
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
    pattern: str = typer.Argument(..., help="Command pattern to deny")
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
    level: str = typer.Argument(..., help="Permission level (allow, deny, ask)")
):
    """
    Set the default permission level for a tool.
    """
    try:
        perm_level = PermissionLevel(level.lower())
    except ValueError:
        print_error(f"Invalid level: {level}. Use: allow, deny, or ask")
        raise typer.Exit(1)

    permissions = get_permissions()
    permissions.set_tool_permission(tool, perm_level)
    print_success(f"Set {tool} permission to: {perm_level.value}")


@permissions_app.command("reset")
def permissions_reset(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")
):
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
