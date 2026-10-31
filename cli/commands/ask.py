"""ask command — non-interactive single-shot query."""

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
from core.mentions import expand_mentions
from core.modes import AgentMode
from core.project_context import ProjectContextLoader
from core.skills import SkillManager, render_prompt
from utils.logger import print_error, print_warning


def ask(
    prompt: str = typer.Argument(None, help="The prompt or question for DevOrch"),
    provider: str = typer.Option(None, "--provider", "-p", help="LLM Provider"),
    model: str = typer.Option(None, "--model", "-m", help="Model name"),
    skill: str = typer.Option(
        None, "--skill", "-s", help="Run a named skill (e.g. commit, review)"
    ),
    mode: str = typer.Option(None, "--mode", help="Execution mode: ask, auto, plan"),
    no_mcp: bool = typer.Option(False, "--no-mcp", help="Disable all MCP servers for this run"),
    mcp: list[str] = typer.Option(None, "--mcp", help="Use only these MCP servers (repeatable)"),
    output: str = typer.Option(
        "text", "--output", "-o", help="Output format: text, json, stream-json"
    ),
):
    """
    Ask DevOrch a single question (non-interactive).

    Examples:
      devorch ask "explain this project"
      devorch ask --skill commit
      devorch ask --skill review "focus on security"
      devorch ask --mode auto "run the tests"
      devorch ask --no-mcp "quick question"
      devorch ask --mcp github --mcp filesystem "..."
      devorch ask --output json "list the TODOs" | jq .result
    """
    output = validate_format(output)
    configure_output(output)
    settings = Settings.load()
    print_project_notices(settings)

    if not provider:
        provider = settings.default_provider

    llm = create_provider(provider, model, settings)
    tools = build_tools(settings, no_mcp=no_mcp, mcp_only=mcp or None)
    agent_mode = resolve_mode(mode, default=AgentMode.AUTO)
    memory_ctx = MemoryManager().get_context_prompt()
    project_ctx = ProjectContextLoader().load()
    project_prompt = project_ctx.to_system_prompt_block() if project_ctx else ""
    agent = build_agent(llm, tools, memory_ctx, agent_mode, project_ctx=project_prompt)

    skill_manager = SkillManager()
    if skill:
        skill_data = skill_manager.get(skill)
        if not skill_data:
            available = ", ".join(s["name"] for s in skill_manager.list_skills())
            print_error(f"Unknown skill '{skill}'. Available: {available}")
            raise typer.Exit(1)
        final_prompt = render_prompt(skill_data, prompt)
        console.print(f"[dim]Skill: {skill} | {llm.name}/{llm.model}[/dim]")
    else:
        if not prompt:
            print_error("Provide a prompt or use --skill <name>.")
            raise typer.Exit(1)
        final_prompt = prompt
        console.print(f"[dim]Using {llm.name}/{llm.model}[/dim]")

    mentions = expand_mentions(final_prompt)
    for warning in mentions.warnings:
        print_warning(warning)
    run_with_output(
        agent,
        mentions.prompt,
        output=output,
        provider=llm.name,
        model=llm.model,
        title="DevOrch",
        images=mentions.images,
    )
