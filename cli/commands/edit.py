"""edit command — target a specific file for AI-driven editing."""

import typer

from cli.commands._shared import build_agent, build_tools, console, create_provider, resolve_mode
from config.settings import Settings
from core.memory import MemoryManager
from utils.logger import print_error, print_panel


def edit(
    file: str = typer.Argument(..., help="File path to edit"),
    instruction: str = typer.Argument(..., help="What to change in the file"),
    provider: str = typer.Option(None, "--provider", "-p", help="LLM Provider"),
    model: str = typer.Option(None, "--model", "-m", help="Model name"),
    mode: str = typer.Option("auto", "--mode", help="Execution mode: ask, auto, plan"),
    no_mcp: bool = typer.Option(False, "--no-mcp", help="Disable all MCP servers for this run"),
    mcp: list[str] = typer.Option(None, "--mcp", help="Use only these MCP servers (repeatable)"),
):
    """
    Edit a specific file using an AI instruction.

    Examples:
      devorch edit src/auth.py "add input validation to the login function"
      devorch edit README.md "update the installation section"
      devorch edit app/models.py "add a created_at timestamp field to User"
      devorch edit src/db.py "add indexes" --mcp sqlite
    """
    settings = Settings.load()

    if not provider:
        provider = settings.default_provider

    llm = create_provider(provider, model, settings)
    # edit only needs file-oriented tools — no terminal/task tools
    tools = build_tools(settings, include_terminal=False, no_mcp=no_mcp, mcp_only=mcp or None)
    agent_mode = resolve_mode(mode)
    memory_ctx = MemoryManager().get_context_prompt()
    agent = build_agent(llm, tools, memory_ctx, agent_mode)

    prompt = (
        f"Edit the file `{file}` with the following instruction:\n\n"
        f"{instruction}\n\n"
        "Read the file first, then make the minimal targeted changes needed. Show the diff when done."
    )

    console.print(f"[dim]Editing {file} | {llm.name}/{llm.model}[/dim]")
    try:
        result = agent.run(prompt, max_iterations=10)
        print_panel(result, title=f"DevOrch — edit {file}", border_style="cyan")
    except Exception as e:
        print_error(str(e))
