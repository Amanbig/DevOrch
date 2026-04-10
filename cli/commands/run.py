"""run command — shorthand for executing a named skill directly."""

import typer

from cli.commands._shared import build_agent, build_tools, console, create_provider, resolve_mode
from config.settings import Settings
from core.memory import MemoryManager
from core.skills import SkillManager
from utils.logger import print_error, print_panel


def run(
    skill_name: str = typer.Argument(..., help="Skill name to run (e.g. commit, review, test)"),
    extra: str = typer.Argument(None, help="Optional extra context appended to the skill prompt"),
    provider: str = typer.Option(None, "--provider", "-p", help="LLM Provider"),
    model: str = typer.Option(None, "--model", "-m", help="Model name"),
    mode: str = typer.Option("auto", "--mode", help="Execution mode: ask, auto, plan"),
    no_mcp: bool = typer.Option(False, "--no-mcp", help="Disable all MCP servers for this run"),
    mcp: list[str] = typer.Option(None, "--mcp", help="Use only these MCP servers (repeatable)"),
):
    """
    Run a skill directly.

    Examples:
      devorch run commit
      devorch run review
      devorch run test "only run unit tests"
      devorch run commit --no-mcp
      devorch run review --mcp github
    """
    settings = Settings.load()

    if not provider:
        provider = settings.default_provider

    llm = create_provider(provider, model, settings)

    skill_manager = SkillManager()
    skill_data = skill_manager.get(skill_name)
    if not skill_data:
        available = ", ".join(s["name"] for s in skill_manager.list_skills())
        print_error(f"Unknown skill '{skill_name}'. Available: {available}")
        raise typer.Exit(1)

    final_prompt = skill_data["prompt"]
    if extra:
        final_prompt = f"{final_prompt}\n\n{extra}"

    tools = build_tools(settings, no_mcp=no_mcp, mcp_only=mcp or None)
    agent_mode = resolve_mode(mode)
    memory_ctx = MemoryManager().get_context_prompt()
    agent = build_agent(llm, tools, memory_ctx, agent_mode)

    console.print(f"[dim]Skill: {skill_name} | {llm.name}/{llm.model}[/dim]")
    try:
        result = agent.run(final_prompt, max_iterations=15)
        print_panel(result, title=f"DevOrch — {skill_name}", border_style="cyan")
    except Exception as e:
        print_error(str(e))
