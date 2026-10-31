"""Tests for the slash commands that mirror the CLI, and the skip-permissions flag."""

import io
import re
from pathlib import Path

import pytest
import typer
from rich.console import Console

from cli import repl_commands as rc
from cli.commands._shared import resolve_mode
from config import permissions as perm_mod
from config.permissions import PermissionLevel, Permissions
from config.project_settings import is_trusted
from core import sessions as sessions_mod
from core.executor import ToolExecutor
from core.modes import AgentMode, ModeManager
from core.sessions import SessionManager
from tools.shell import ShellTool
from utils import logger


def clear(buf: io.StringIO) -> None:
    """Empty a StringIO. truncate(0) alone keeps the write position, so the next write is padded
    with NUL characters."""
    buf.seek(0)
    buf.truncate(0)


@pytest.fixture
def out(monkeypatch):
    buf = io.StringIO()
    con = Console(file=buf, width=2000, force_terminal=False, color_system=None)
    monkeypatch.setattr(rc, "console", con)
    monkeypatch.setattr(logger, "console", con)
    return buf


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    (h / ".devorch").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: h)
    monkeypatch.setattr(perm_mod, "CONFIG_DIR", h / ".devorch")
    monkeypatch.setattr(perm_mod, "PERMISSIONS_FILE", h / ".devorch" / "permissions.yaml")
    monkeypatch.setattr(perm_mod, "_permissions", None)
    monkeypatch.setattr(sessions_mod, "DATA_DIR", h / ".devorch")
    monkeypatch.setattr(sessions_mod, "DB_PATH", h / ".devorch" / "sessions.db")
    return h


# ── /permissions ────────────────────────────────────────────────────────────


def test_permissions_list_is_default(home, out):
    rc.handle_permissions("", Permissions.load())
    assert "Tool Permissions" in out.getvalue() and "shell" in out.getvalue()
    clear(out)
    rc.handle_permissions("list", Permissions.load())
    assert "Tool Permissions" in out.getvalue()


def test_allow_and_deny_patterns_with_spaces_and_quotes(home, out):
    perms = Permissions.load()
    rc.handle_permissions("allow shell git log *", perms)
    rc.handle_permissions('deny shell "git push*"', perms)
    assert "git log *" in perms.tools["shell"].allowed_patterns
    assert "git push*" in perms.tools["shell"].denied_patterns
    # persisted
    again = Permissions.load()
    assert "git log *" in again.tools["shell"].allowed_patterns


def test_session_flag_is_not_persisted(home, out):
    perms = Permissions.load()
    rc.handle_permissions("allow --session shell pytest*", perms)
    assert "pytest*" in perms.session_allowed or any("pytest" in p for p in perms.session_allowed)
    assert "pytest*" not in Permissions.load().tools["shell"].allowed_patterns
    assert "for this session" in out.getvalue()


def test_set_level_and_validation(home, out):
    perms = Permissions.load()
    rc.handle_permissions("set filesystem allow", perms)
    assert perms.tools["filesystem"].level == PermissionLevel.ALLOW
    rc.handle_permissions("set filesystem sometimes", perms)
    assert "Invalid level" in out.getvalue()
    assert perms.tools["filesystem"].level == PermissionLevel.ALLOW


def test_permissions_argument_errors(home, out):
    perms = Permissions.load()
    for arg in ("allow shell", "deny", "set shell", "bogus x", 'allow shell "unterminated'):
        clear(out)
        rc.handle_permissions(arg, perms)
        assert (
            "Usage" in out.getvalue() or "Unknown" in out.getvalue() or "parse" in out.getvalue()
        ), arg


def test_permissions_reset_needs_confirmation(home, out):
    perms = Permissions.load()
    rc.handle_permissions("allow shell make *", perms)
    rc.handle_permissions("reset", perms, confirm=lambda m: False)
    assert "Cancelled" in out.getvalue() and "make *" in perms.tools["shell"].allowed_patterns
    rc.handle_permissions("reset", perms, confirm=lambda m: True)
    assert "make *" not in perms.tools["shell"].allowed_patterns  # live object reset too
    assert not perm_mod.PERMISSIONS_FILE.exists()


# ── /sessions ───────────────────────────────────────────────────────────────


def _sessions(home):
    sm = SessionManager()
    a = sm.create_session("openai", "gpt-4o", name="first")
    b = sm.create_session("anthropic", "claude", name="second")
    return sm, a, b


def test_sessions_list_marks_current(home, out):
    sm, a, b = _sessions(home)
    rc.handle_sessions("", sm, b)
    text = out.getvalue()
    assert a in text and b in text and "current" in text and "--resume" in text


def test_sessions_list_count_validation(home, out):
    sm, *_ = _sessions(home)
    rc.handle_sessions("list abc", sm, None)
    assert "Usage" in out.getvalue()


def test_sessions_show(home, out):
    sm, a, _ = _sessions(home)
    rc.handle_sessions(f"show {a}", sm, None)
    assert "gpt-4o" in out.getvalue()
    clear(out)
    rc.handle_sessions("show nope", sm, None)
    assert "not found" in out.getvalue().lower() or "Error" in out.getvalue()


def test_sessions_delete_rules(home, out):
    sm, a, b = _sessions(home)
    rc.handle_sessions(f"delete {b}", sm, b)  # the current one
    assert "current session" in out.getvalue() and sm.session_exists(b)
    rc.handle_sessions(f"delete {a}", sm, b, confirm=lambda m: False)
    assert sm.session_exists(a)
    rc.handle_sessions(f"delete {a}", sm, b, confirm=lambda m: True)
    assert not sm.session_exists(a)
    clear(out)
    rc.handle_sessions("delete nope", sm, b, confirm=lambda m: True)
    assert "not found" in out.getvalue()


def test_sessions_bad_usage(home, out):
    sm, *_ = _sessions(home)
    for arg in ("show", "delete", "frobnicate"):
        clear(out)
        rc.handle_sessions(arg, sm, None)
        assert "Usage" in out.getvalue(), arg


# ── /hooks, /trust, /untrust ────────────────────────────────────────────────


@pytest.fixture
def project(home, monkeypatch):
    proj = home / "proj"
    (proj / ".devorch").mkdir(parents=True)
    (proj / ".devorch" / "hooks.yaml").write_text(
        "hooks:\n  PreToolUse:\n    - matcher: shell\n      command: ./guard.sh\n"
    )
    (proj / ".devorch" / "settings.yaml").write_text("default_mode: ask\n")
    monkeypatch.chdir(proj)
    return proj


def test_hooks_untrusted_project_shows_notice_not_hooks(project, out):
    rc.handle_hooks(project)
    text = out.getvalue()
    assert "guard.sh" not in text and "untrusted" in text and "No active hooks" in text


def test_hooks_trusted_project_lists_them(project, out):
    rc.trust_root(project)
    rc.handle_hooks(project)
    assert "PreToolUse" in out.getvalue() and "./guard.sh" in out.getvalue()


def test_trust_declined_then_accepted_then_revoked(project, out):
    assert rc.handle_trust(lambda m: False, project) is False and not is_trusted(project)
    assert "guard.sh" in out.getvalue()  # the file is shown before asking
    assert rc.handle_trust(lambda m: True, project) is True and is_trusted(project)
    rc.handle_untrust(project)
    assert not is_trusted(project)
    clear(out)
    rc.handle_untrust(project)
    assert "was not trusted" in out.getvalue()


def test_trust_without_project_files(home, out, tmp_path, monkeypatch):
    empty = home / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    assert rc.handle_trust(lambda m: True, empty) is False
    assert "No .devorch" in out.getvalue()


def test_trust_prints_yaml_brackets_literally(project, out):
    (project / ".devorch" / "settings.yaml").write_text(
        'mcp_servers:\n  x:\n    command: c\n    args: ["-y", "[/bold]"]\n'
    )
    rc.handle_trust(lambda m: False, project)
    assert "[/bold]" in out.getvalue()


# ── --dangerously-skip-permissions / --mode ─────────────────────────────────


def test_skip_permissions_means_auto(home):
    assert resolve_mode(None, default=AgentMode.ASK, skip_permissions=True) == AgentMode.AUTO
    assert resolve_mode("auto", skip_permissions=True) == AgentMode.AUTO


def test_skip_permissions_conflicts_with_other_modes(home):
    with pytest.raises(typer.Exit) as exc:
        resolve_mode("ask", skip_permissions=True)
    assert exc.value.exit_code == 1


def test_skip_permissions_overrides_project_default_mode(home, project):
    assert resolve_mode(None, default=AgentMode.ASK) == AgentMode.ASK  # project says ask
    assert resolve_mode(None, default=AgentMode.ASK, skip_permissions=True) == AgentMode.AUTO


def test_mode_flag_still_works(home):
    assert resolve_mode("plan", default=AgentMode.ASK) == AgentMode.PLAN


def test_skipping_prompts_still_enforces_deny_rules_and_dangerous_blocks(home):
    # AUTO (what the flag selects) must never prompt, yet blocked commands stay blocked
    perms = Permissions.load()
    perms.add_denied_pattern("shell", "git push*", session_only=True)
    ex = ToolExecutor(
        [ShellTool()],
        require_confirmation=True,
        permissions=perms,
        mode_manager=ModeManager(default_mode=AgentMode.AUTO),
    )

    def no_prompt(*a, **k):
        raise AssertionError("a permission prompt was shown in AUTO mode")

    ex._ask_permission = no_prompt
    assert "hello" in ex.execute("shell", {"command": "echo hello"})
    assert "denied" in ex.execute("shell", {"command": "git push origin main"}).lower()
    assert "denied" in ex.execute("shell", {"command": "rm -rf *"}).lower()


def _option_names(command) -> set[str]:
    return {opt for param in command.params for opt in getattr(param, "opts", [])}


def test_flag_is_available_on_every_entry_point():
    # Inspect the registered options, not the --help text: help output is colourised, wrapped to the
    # terminal width and truncated, so substring checks on it break between environments (CI).
    import typer.main

    from cli.main import app

    root = typer.main.get_command(app)
    entry_points = {
        "devorch": root,
        **{name: root.commands[name] for name in ("chat", "ask", "run", "edit")},
    }
    for name, command in entry_points.items():
        options = _option_names(command)
        assert "--dangerously-skip-permissions" in options, name
        assert "--mode" in options, name


def test_flag_is_a_boolean_switch_with_help_text():
    import typer.main

    from cli.main import app

    ask = typer.main.get_command(app).commands["ask"]
    flag = next(p for p in ask.params if "--dangerously-skip-permissions" in p.opts)
    assert flag.is_flag and flag.default is False
    assert "same as --mode auto" in flag.help


# ── dropdown <-> dispatcher consistency ─────────────────────────────────────


def test_every_slash_command_in_the_dropdown_has_a_handler():
    from cli.constants import SLASH_COMMANDS

    source = (
        Path(__file__).resolve().parents[1].joinpath("cli", "main.py").read_text(encoding="utf-8")
    )
    for cmd in SLASH_COMMANDS:
        name = cmd[1:]
        pattern = rf'"{re.escape(name)}"|"{re.escape(cmd)}"'
        assert re.search(pattern, source), f"{cmd} is offered in the dropdown but never handled"
