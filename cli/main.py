import typer

from core.agent import Agent
from core.executor import ToolExecutor
from providers import get_provider, PROVIDERS
from config.settings import Settings
from utils.logger import get_console, print_error, print_success, print_panel, print_warning

from tools.shell import ShellTool
from tools.filesystem import FilesystemTool
from tools.search import SearchTool

from core.planner import Planner
from schemas.message import Message
from typing import List


class SimplePlanner(Planner):
    def plan(self, history: List[Message]) -> List[Message]:
        system_prompt = Message(
            role="system",
            content="You are DevPilot, an AI coding assistant. You have access to tools to interact with the local machine. Use them to help the user."
        )
        return [system_prompt] + history


app = typer.Typer(help="DevPilot - Your AI Coding Assistant")
console = get_console()


def create_provider(provider_name: str, model: str, settings: Settings):
    """Create and validate a provider instance."""
    provider_name = provider_name.lower()

    if provider_name not in PROVIDERS:
        print_error(f"Unknown provider '{provider_name}'. Available: {', '.join(PROVIDERS.keys())}")
        raise typer.Exit(1)

    # Get API key from settings (which checks env vars)
    api_key = settings.get_api_key(provider_name)

    # Validate API key is present (except for local)
    if provider_name != "local" and not api_key:
        env_var_name = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GOOGLE_API_KEY",
        }.get(provider_name, f"{provider_name.upper()}_API_KEY")

        print_error(f"No API key found for {provider_name}.")
        print_error(f"Set {env_var_name} environment variable or configure in ~/.devpilot/config.yaml")
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
    model: str = typer.Option(None, "--model", "-m", help="Model name to use")
):
    """
    Start an interactive DevPilot REPL session.
    """
    settings = Settings.load()

    if not provider:
        provider = settings.default_provider

    llm = create_provider(provider, model, settings)

    tools = [ShellTool(), FilesystemTool(), SearchTool()]
    executor = ToolExecutor(tools=tools, require_confirmation=True)
    planner = SimplePlanner()

    agent = Agent(provider=llm, planner=planner, executor=executor, tools=tools)

    print_panel(
        f"Welcome to DevPilot REPL!\nProvider: {llm.name} | Model: {llm.model}\nType 'exit' or 'quit' to leave.",
        title="DevPilot",
        border_style="blue",
        fit=True
    )

    while True:
        try:
            user_input = typer.prompt("You")

            if user_input.lower() in ("exit", "quit", "q"):
                print_warning("Goodbye!")
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
    console.print("\n[bold]Configured Providers:[/bold]")

    for name in PROVIDERS.keys():
        provider_config = settings.providers.get(name)
        if provider_config:
            has_key = "[green]configured[/green]" if provider_config.api_key else "[yellow]not set[/yellow]"
            if name == "local":
                has_key = "[dim]not required[/dim]"
            model = provider_config.default_model or "default"
            console.print(f"  [bold]{name}[/bold]: {model} (API key: {has_key})")


@app.command()
def providers():
    """
    List available providers.
    """
    console.print("[bold]Available Providers:[/bold]\n")
    for name in PROVIDERS.keys():
        console.print(f"  - {name}")


def main():
    app()


if __name__ == "__main__":
    main()
