import typer
from typing import List, Optional
from rich.table import Table

from core.agent import Agent
from core.executor import ToolExecutor
from core.sessions import SessionManager
from providers import get_provider, PROVIDERS
from config.settings import Settings, set_api_key, keyring_available
from utils.logger import get_console, print_error, print_success, print_panel, print_warning, print_info

from tools.shell import ShellTool
from tools.filesystem import FilesystemTool
from tools.search import SearchTool

from core.planner import Planner
from schemas.message import Message


class SimplePlanner(Planner):
    def plan(self, history: List[Message]) -> List[Message]:
        system_prompt = Message(
            role="system",
            content="You are DevPilot, an AI coding assistant. You have access to tools to interact with the local machine. Use them to help the user."
        )
        return [system_prompt] + history


app = typer.Typer(help="DevPilot - Your AI Coding Assistant")
sessions_app = typer.Typer(help="Manage chat sessions")
app.add_typer(sessions_app, name="sessions")

console = get_console()


def create_provider(provider_name: str, model: str, settings: Settings):
    """Create and validate a provider instance."""
    provider_name = provider_name.lower()

    if provider_name not in PROVIDERS:
        print_error(f"Unknown provider '{provider_name}'. Available: {', '.join(PROVIDERS.keys())}")
        raise typer.Exit(1)

    # Get API key from settings (which checks keyring and env vars)
    api_key = settings.get_api_key(provider_name)

    # Validate API key is present (except for local)
    if provider_name != "local" and not api_key:
        env_var_name = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GOOGLE_API_KEY",
        }.get(provider_name, f"{provider_name.upper()}_API_KEY")

        print_error(f"No API key found for {provider_name}.")
        print_error(f"Use 'devpilot set-key {provider_name}' or set {env_var_name} environment variable")
        raise typer.Exit(1)

    # Use default model if not specified
    if not model:
        model = settings.get_default_model(provider_name)

    # Create provider with optional kwargs for local
    kwargs = {}
    if provider_name == "local":
        base_url = settings.get_base_url(provider_name)
        if base_url:
            kwargs["base_url"] = base_url

    return get_provider(provider_name, model=model, api_key=api_key, **kwargs)


@app.command()
def ask(
    prompt: str = typer.Argument(..., help="The prompt or question for DevPilot"),
    provider: str = typer.Option(None, "--provider", "-p", help="LLM Provider (openai, anthropic, gemini, local)"),
    model: str = typer.Option(None, "--model", "-m", help="Model name to use")
):
    """
    Ask DevPilot a single question or give it a task.
    """
    settings = Settings.load()

    # Use default provider if not specified
    if not provider:
        provider = settings.default_provider

    llm = create_provider(provider, model, settings)

    tools = [ShellTool(), FilesystemTool(), SearchTool()]
    executor = ToolExecutor(tools=tools)
    planner = SimplePlanner()

    agent = Agent(
        provider=llm,
        planner=planner,
        executor=executor,
        tools=tools
    )

    console.print(f"[bold blue]DevPilot ({llm.name}/{llm.model}) is thinking...[/bold blue]")
    try:
        result = agent.run(prompt, max_iterations=15)
        print_success("Response:")
        print_panel(result, title="DevPilot Response", border_style="green")
    except Exception as e:
        print_error(str(e))


@app.command()
def repl(
    provider: str = typer.Option(None, "--provider", "-p", help="LLM Provider (openai, anthropic, gemini, local)"),
    model: str = typer.Option(None, "--model", "-m", help="Model name to use"),
    resume: str = typer.Option(None, "--resume", "-r", help="Resume a previous session by ID")
):
    """
    Start an interactive DevPilot REPL session.
    """
    settings = Settings.load()
    session_manager = SessionManager()

    # Handle session resumption
    if resume:
        try:
            session_info, messages = session_manager.load_session(resume)
            provider = session_info["provider"]
            model = session_info["model"]
            print_success(f"Resumed session: {resume}")
            print_info(f"Provider: {provider} | Model: {model} | Messages: {len(messages)}")
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
        print_info(f"Session ID: {session_id}")

    tools = [ShellTool(), FilesystemTool(), SearchTool()]
    executor = ToolExecutor(tools=tools, require_confirmation=True)
    planner = SimplePlanner()

    agent = Agent(
        provider=llm,
        planner=planner,
        executor=executor,
        tools=tools,
        session_manager=session_manager
    )

    # Restore history if resuming
    if messages:
        agent.set_history(messages)

    print_panel(
        f"Welcome to DevPilot REPL!\nProvider: {llm.name} | Model: {llm.model}\nSession: {session_manager.current_session_id}\nType 'exit' or 'quit' to leave.",
        title="DevPilot",
        border_style="blue",
        fit=True
    )

    while True:
        try:
            user_input = typer.prompt("You")

            if user_input.lower() in ("exit", "quit", "q"):
                print_warning("Goodbye!")
                print_info(f"Session saved: {session_manager.current_session_id}")
                break

            if not user_input.strip():
                continue

            result = agent.run(user_input, max_iterations=15)
            print_panel(result, title="DevPilot", border_style="green")

        except typer.Abort:
            print_warning("Aborted.")
            break
        except Exception as e:
            print_error(str(e))


@app.command()
def config():
    """
    Show current configuration.
    """
    settings = Settings.load()

    console.print("[bold]DevPilot Configuration[/bold]\n")
    console.print(f"Default Provider: [cyan]{settings.default_provider}[/cyan]")
    console.print(f"Keyring Available: {'[green]yes[/green]' if keyring_available() else '[yellow]no[/yellow]'}")
    console.print("\n[bold]Configured Providers:[/bold]")

    for name in PROVIDERS.keys():
        provider_config = settings.providers.get(name)
        if provider_config:
            if name == "local":
                key_status = "[dim]not required[/dim]"
            elif provider_config.api_key:
                if provider_config.key_encrypted:
                    key_status = "[green]configured (encrypted)[/green]"
                else:
                    key_status = "[green]configured (env var)[/green]"
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

    # Prompt for key securely (hidden input)
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
    console.print("[bold]Available Providers:[/bold]\n")
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
    table.add_column("Messages", justify="right")
    table.add_column("Updated", style="dim")

    for session in sessions:
        table.add_row(
            session["id"],
            session["name"] or "-",
            session["provider"],
            session["model"],
            str(session["message_count"]),
            session["updated_at"]
        )

    console.print(table)


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


def main():
    app()


if __name__ == "__main__":
    main()
