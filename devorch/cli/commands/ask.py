"""ask command — non-interactive single-shot query."""

import typer

from devorch.cli.commands._output import (
    configure_output,
    run_with_output,
    stdio_approver,
    validate_format,
)
from devorch.cli.commands._shared import (
    SKIP_PERMISSIONS_HELP,
    build_agent,
    build_tools,
    console,
    create_provider,
    print_project_notices,
    resolve_mode,
)
from devorch.config.settings import Settings
from devorch.core.memory import MemoryManager
from devorch.core.mentions import expand_mentions
from devorch.core.modes import AgentMode
from devorch.core.project_context import ProjectContextLoader
from devorch.core.sessions import SessionManager
from devorch.core.skills import SkillManager, render_prompt
from devorch.utils.logger import print_error, print_warning


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
    skip_permissions: bool = typer.Option(
        False, "--dangerously-skip-permissions", help=SKIP_PERMISSIONS_HELP
    ),
    resume: str = typer.Option(None, "--resume", "-r", help="Continue this saved session by ID"),
    continue_session: bool = typer.Option(
        False, "--continue", "-c", help="Continue the latest session in this directory"
    ),
    save_session: bool = typer.Option(
        False,
        "--save-session",
        help="Save this run as a session you can continue (always on with --resume/--continue)",
    ),
    approvals: str = typer.Option(
        "terminal",
        "--approvals",
        help="Where permission questions are answered: terminal (default) or stdio "
        "(JSON lines, for editors; needs --output stream-json)",
    ),
    max_turns: int = typer.Option(
        None,
        "--max-turns",
        min=1,
        max=200,
        help="Most model/tool steps before stopping (default 15)",
    ),
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
      devorch ask --save-session -o json "start here"      (result has a session_id)
      devorch ask --resume <session_id> "and then?"
      devorch ask --continue "keep going"
    """
    output = validate_format(output)
    if approvals not in ("terminal", "stdio"):
        print_error("--approvals must be 'terminal' or 'stdio'.")
        raise typer.Exit(2)
    if approvals == "stdio" and output != "stream-json":
        print_error("--approvals stdio needs --output stream-json.")
        raise typer.Exit(2)
    configure_output(output)
    settings = Settings.load()
    print_project_notices(settings)

    sessions = None
    history, summary = [], None
    if resume or continue_session or save_session:
        sessions = SessionManager()
        sid = resume or (sessions.latest_session_id() if continue_session else None)
        if continue_session and not resume and sid is None:
            print_warning("No earlier conversation in this directory; starting a new session.")
        if sid:
            try:
                info, history = sessions.load_session(sid)
            except ValueError as e:
                print_error(str(e))
                raise typer.Exit(1) from e
            # the saved session's provider and model apply unless this run names its own
            provider = provider or info["provider"]
            model = model or info["model"]
            summary = info.get("summary")

    if not provider:
        provider = settings.default_provider

    llm = create_provider(provider, model, settings)
    if sessions is not None and not sessions.current_session_id:
        sessions.create_session(llm.name, llm.model)
    tools = build_tools(settings, no_mcp=no_mcp, mcp_only=mcp or None)
    agent_mode = resolve_mode(mode, default=AgentMode.AUTO, skip_permissions=skip_permissions)
    memory_ctx = MemoryManager().get_context_prompt()
    project_ctx = ProjectContextLoader().load()
    project_prompt = project_ctx.to_system_prompt_block() if project_ctx else ""
    agent = build_agent(
        llm,
        tools,
        memory_ctx,
        agent_mode,
        project_ctx=project_prompt,
        pricing=settings.pricing,
        context_windows=settings.context_windows,
    )

    if approvals == "stdio":
        agent.executor.approver = stdio_approver()
    if sessions is not None:
        agent.session_manager = sessions
        if history:
            agent.set_history(history)
        if summary:
            agent.set_context_summary(summary)

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
        max_iterations=max_turns or 15,
    )
    if output == "text" and sessions is not None and sessions.current_session_id:
        sid = sessions.current_session_id
        console.print(f'[dim]Session {sid}: continue with devorch ask --resume {sid} "..."[/dim]')
