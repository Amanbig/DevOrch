"""Slash-command handlers that mirror the non-interactive CLI (`devorch permissions|sessions|trust`).

Each handler prints through ``console`` and takes its collaborators as arguments, so it can be tested
without a running REPL. The CLI commands call the same functions where they share logic.
"""

import shlex
from collections.abc import Callable
from pathlib import Path

from rich.table import Table

from config.permissions import PermissionLevel, Permissions
from config.project_settings import (
    is_trusted,
    project_trust_files,
    trust_root,
    untrust_project,
)
from core.hooks import HookManager
from utils.logger import get_console, print_error, print_info, print_success, print_warning

console = get_console()

Confirm = Callable[[str], bool]

PERMISSIONS_USAGE = (
    "Usage: /permissions [list]\n"
    "       /permissions allow [--session] <tool> <pattern>   e.g. /permissions allow shell git *\n"
    "       /permissions deny  [--session] <tool> <pattern>\n"
    "       /permissions set <tool> <allow|deny|ask>\n"
    "       /permissions reset"
)


# ── permissions ─────────────────────────────────────────────────────────────


def show_permissions(perms: Permissions) -> None:
    level_color = {"allow": "green", "deny": "red", "ask": "yellow"}
    console.print("\n[bold]Tool Permissions[/bold]")
    for tool_name, perm in perms.tools.items():
        color = level_color.get(perm.level.value, "white")
        counts = []
        if perm.allowed_patterns:
            counts.append(f"{len(perm.allowed_patterns)} allowed patterns")
        if perm.denied_patterns:
            counts.append(f"{len(perm.denied_patterns)} denied patterns")
        extra = f" [dim]({', '.join(counts)})[/dim]" if counts else ""
        console.print(f"  {tool_name}: [{color}]{perm.level.value}[/{color}]{extra}")
    if perms.session_allowed:
        console.print(f"\n[green]Session allowed:[/green] {len(perms.session_allowed)} patterns")
    if perms.session_denied:
        console.print(f"[red]Session denied:[/red] {len(perms.session_denied)} patterns")
    console.print("[dim]  Details and changes: /permissions allow|deny|set|reset[/dim]\n")


def handle_permissions(arg: str | None, perms: Permissions, confirm: Confirm | None = None) -> None:
    try:
        tokens = shlex.split(arg or "")
    except ValueError as e:
        print_error(f"Could not parse arguments: {e}")
        return
    if not tokens or tokens[0] == "list":
        show_permissions(perms)
        return

    action, rest = tokens[0].lower(), tokens[1:]
    session_only = "--session" in rest
    rest = [t for t in rest if t != "--session"]

    if action in ("allow", "deny"):
        if len(rest) < 2:
            print_error(f"/permissions {action} needs a tool and a pattern.")
            print_info(PERMISSIONS_USAGE)
            return
        tool, pattern = rest[0], " ".join(rest[1:])
        if action == "allow":
            perms.add_allowed_pattern(tool, pattern, session_only=session_only)
        else:
            perms.add_denied_pattern(tool, pattern, session_only=session_only)
        scope = "for this session" if session_only else "(saved)"
        print_success(f"{action.capitalize()}ed {tool}: {pattern} {scope}")
        return

    if action == "set":
        if len(rest) != 2:
            print_error("/permissions set needs a tool and a level.")
            print_info(PERMISSIONS_USAGE)
            return
        try:
            level = PermissionLevel(rest[1].lower())
        except ValueError:
            print_error(f"Invalid level '{rest[1]}'. Use: allow, deny or ask.")
            return
        perms.set_tool_permission(rest[0], level)
        print_success(f"Set {rest[0]} permission to: {level.value}")
        return

    if action == "reset":
        from config.permissions import get_permissions, reset_permissions

        if confirm is not None and not confirm("Reset all permissions to defaults?"):
            print_warning("Cancelled.")
            return
        reset_permissions()
        # keep the live object in sync so the rest of this session uses the defaults too
        fresh = get_permissions()
        perms.tools = fresh.tools
        perms.session_allowed = []
        perms.session_denied = []
        print_success("Permissions reset to defaults.")
        return

    print_error(f"Unknown /permissions action '{action}'.")
    print_info(PERMISSIONS_USAGE)


# ── sessions ────────────────────────────────────────────────────────────────


def print_sessions_table(session_manager, limit: int = 20, current_id: str | None = None) -> None:
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
        sid = session["id"]
        table.add_row(
            sid + (" ◀ current" if sid == current_id else ""),
            (session["name"] or "-")[:20],
            session["provider"],
            session["model"],
            str(session["message_count"]),
            session.get("parent_session_id") or "-",
            str(session["updated_at"])[:16],
        )
    console.print(table)


def print_session_details(session_manager, session_id: str) -> bool:
    try:
        info, messages = session_manager.load_session(session_id)
    except ValueError as e:
        print_error(str(e))
        return False
    console.print(f"\n[bold]Session: {session_id}[/bold]", highlight=False)
    console.print(f"Name: {info.get('name') or '-'}", highlight=False)
    console.print(f"Provider: {info['provider']}", highlight=False)
    console.print(f"Model: {info['model']}", highlight=False)
    console.print(f"Messages: {len(messages)}", highlight=False)
    if info.get("parent_session_id"):
        console.print(f"Parent: {info['parent_session_id']}", highlight=False)
    if info.get("summary"):
        summary = info["summary"]
        console.print("\n[bold]Context summary:[/bold]")
        console.print(summary[:500] + ("..." if len(summary) > 500 else ""), markup=False)
    return True


def handle_sessions(
    arg: str | None, session_manager, current_id: str | None, confirm: Confirm | None = None
) -> None:
    tokens = (arg or "").split()
    action = tokens[0].lower() if tokens else "list"
    if action == "list":
        limit = 20
        if len(tokens) > 1:
            if not tokens[1].isdigit():
                print_error("Usage: /sessions list [count]")
                return
            limit = max(1, int(tokens[1]))
        print_sessions_table(session_manager, limit, current_id)
        console.print("[dim]  Resume a session with: devorch --resume <id>[/dim]\n")
    elif action == "show" and len(tokens) == 2:
        print_session_details(session_manager, tokens[1])
    elif action == "delete" and len(tokens) == 2:
        sid = tokens[1]
        if sid == current_id:
            print_error("That is the current session; it is still in use.")
            return
        if not session_manager.session_exists(sid):
            print_error(f"Session '{sid}' not found.")
            return
        if confirm is not None and not confirm(f"Delete session {sid}?"):
            print_warning("Cancelled.")
            return
        if session_manager.delete_session(sid):
            print_success(f"Session '{sid}' deleted.")
        else:
            print_error("Failed to delete session.")
    else:
        print_error("Usage: /sessions [list [count]] | show <id> | delete <id>")


# ── hooks / trust ───────────────────────────────────────────────────────────


def handle_hooks(cwd: Path | None = None) -> None:
    mgr = HookManager.load(cwd)
    console.print("\n[bold]Hooks[/bold]")
    if not mgr.hooks or not any(mgr.hooks.values()):
        console.print("  [dim]No active hooks.[/dim]")
    for event, hooks in mgr.hooks.items():
        for hook in hooks:
            matcher = hook.matcher or "*"
            line = f"  {event}  [{matcher}]  {hook.command}  ({hook.timeout}s)"
            console.print(line, markup=False, highlight=False)
    for notice in mgr.notices:
        print_warning(notice)
    console.print(
        "[dim]  Configure in ~/.devorch/hooks.yaml or <project>/.devorch/hooks.yaml; "
        "project hooks need /trust.[/dim]\n"
    )


def handle_trust(confirm: Confirm, start: Path | None = None) -> bool:
    """Show the project's settings/hooks files and trust them if confirmed. True if trusted."""
    pairs = project_trust_files(start)
    if not pairs:
        print_warning("No .devorch/settings.yaml or hooks.yaml found here or in a parent folder.")
        return False
    for _root, path in pairs:
        console.print(f"[bold]{path}[/bold]", highlight=False)
        console.print(path.read_text(encoding="utf-8"), markup=False, highlight=False)
    if not confirm(
        "Trust these files? (MCP servers and hooks run programs; allow rules skip prompts)"
    ):
        print_info("Not trusted.")
        return False
    for root in dict.fromkeys(root for root, _ in pairs):
        trust_root(root)
        print_success(f"Trusted {root}. Re-run trust if these files change.")
    return True


def handle_untrust(start: Path | None = None) -> None:
    roots = list(dict.fromkeys(root for root, _ in project_trust_files(start))) or [
        start or Path.cwd()
    ]
    for root in roots:
        if untrust_project(root):
            print_success(f"Revoked trust for {root}")
        else:
            print_info(f"{root} was not trusted.")


def trust_status(start: Path | None = None) -> list[tuple[Path, bool]]:
    return [
        (root, is_trusted(root)) for root in dict.fromkeys(r for r, _ in project_trust_files(start))
    ]
