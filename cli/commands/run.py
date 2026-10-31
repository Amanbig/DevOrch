"""run command — shorthand for executing a named skill directly."""

import typer

from cli.commands._output import configure_output, run_with_output, validate_format
from cli.commands._shared import (
    build_agent,
    build_tools,
    console,
    create_provider,
    print_project_notices,
    resolve_mode,
)
from config.settings import Settings
from core.memory import MemoryManager
from core.project_context import ProjectContextLoader
from core.skills import SkillManager, render_prompt
from utils.logger import print_error


def run(
    skill_name: str = typer.Argument(..., help="Skill name to run (e.g. commit, review, test)"),
    extra: str = typer.Argument(None, help="Optional extra context appended to the skill prompt"),
    provider: str = typer.Option(None, "--provider", "-p", help="LLM Provider"),
    model: str = typer.Option(None, "--model", "-m", help="Model name"),
    mode: str = typer.Option(
        None, "--mode", help="Execution mode: ask, auto, plan (default: project setting, else auto)"
    ),
    no_mcp: bool = typer.Option(False, "--no-mcp", help="Disable all MCP servers for this run"),
    mcp: list[str] = typer.Option(None, "--mcp", help="Use only these MCP servers (repeatable)"),
    output: str = typer.Option(
        "text", "--output", "-o", help="Output format: text, json, stream-json"
    ),
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
    output = validate_format(output)
    configure_output(output)
    settings = Settings.load()
    print_project_notices(settings)

    if not provider:
        provider = settings.default_provider

    llm = create_provider(provider, model, settings)

    skill_manager = SkillManager()
    skill_data = skill_manager.get(skill_name)
    if not skill_data:
        available = ", ".join(s["name"] for s in skill_manager.list_skills())
        print_error(f"Unknown skill '{skill_name}'. Available: {available}")
        raise typer.Exit(1)

    final_prompt = render_prompt(skill_data, extra)

    tools = build_tools(settings, no_mcp=no_mcp, mcp_only=mcp or None)
    agent_mode = resolve_mode(mode)
    memory_ctx = MemoryManager().get_context_prompt()
    project_ctx = ProjectContextLoader().load()
    project_prompt = project_ctx.to_system_prompt_block() if project_ctx else ""
    agent = build_agent(llm, tools, memory_ctx, agent_mode, project_ctx=project_prompt)

    console.print(f"[dim]Skill: {skill_name} | {llm.name}/{llm.model}[/dim]")
    run_with_output(
        agent,
        final_prompt,
        output=output,
        provider=llm.name,
        model=llm.model,
        title=f"DevOrch — {skill_name}",
    )
