"""Tests for `devorch doctor`."""

import sys
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import cli.main as cli_main
from config.permissions import PermissionLevel, Permissions
from config.project_settings import trust_root
from config.settings import Settings
from core import doctor
from core.doctor import FAIL, INFO, OK, WARN, exit_code, run_checks

SECRET = "sk-THIS-MUST-NEVER-BE-PRINTED-1234567890"


def by_name(rows, name):
    return [r for r in rows if r.name == name]


@pytest.fixture
def project(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    (proj / ".devorch").mkdir(parents=True)
    monkeypatch.chdir(proj)
    return proj


def test_every_row_has_a_valid_status_and_the_expected_sections():
    rows = run_checks()
    assert all(r.status in {OK, WARN, FAIL, INFO} for r in rows)
    names = {r.name for r in rows}
    assert {
        "DevOrch",
        "Python",
        "API keys",
        "Default provider",
        "Permissions",
        "git",
        "Terminal",
    } <= names


def test_api_key_values_never_appear(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET + "-2")
    rows = run_checks()
    blob = " ".join(f"{r.name} {r.detail} {r.hint}" for r in rows)
    assert SECRET not in blob and "THIS-MUST-NEVER" not in blob
    (keys,) = by_name(rows, "API keys")
    assert keys.status == OK and "openai" in keys.detail and "anthropic" in keys.detail


def test_cli_output_never_contains_a_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    result = CliRunner().invoke(cli_main.app, ["doctor"])
    assert SECRET not in result.output and "THIS-MUST-NEVER" not in result.output


def test_default_provider_without_a_key_is_a_failure():
    rows = run_checks()  # the test environment has no keys
    (default,) = by_name(rows, "Default provider")
    assert default.status == FAIL and "no API key" in default.detail and "set-key" in default.hint
    assert exit_code(rows) == 1


def test_default_provider_with_a_key_passes(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    rows = run_checks()
    assert by_name(rows, "Default provider")[0].status == OK
    assert exit_code(rows) == 0


def test_local_default_provider_needs_no_key():
    settings = Settings.load()
    settings.default_provider = "local"
    rows = run_checks(settings=settings)
    assert by_name(rows, "Default provider")[0].status == OK


def test_permissions_warning_when_edits_are_pre_approved():
    # the exact situation a stray test run used to leave behind
    perms = Permissions()
    perms.set_tool_permission("edit", PermissionLevel.ALLOW)
    perms.set_tool_permission("filesystem", PermissionLevel.ALLOW)
    (row,) = by_name(run_checks(), "Permissions")
    assert row.status == WARN and "edit" in row.detail and "filesystem" in row.detail
    assert "permissions reset" in row.hint


def test_permissions_ok_with_defaults():
    (row,) = by_name(run_checks(), "Permissions")
    assert row.status == OK


def test_project_trust_is_reported(project):
    (project / ".devorch" / "hooks.yaml").write_text(
        "hooks:\n  PreToolUse:\n    - command: ./g.sh\n"
    )
    (row,) = by_name(run_checks(cwd=project), "Project settings/hooks")
    assert row.status == WARN and "NOT trusted" in row.detail and "devorch trust" in row.hint
    trust_root(project)
    (row,) = by_name(run_checks(cwd=project), "Project settings/hooks")
    assert row.status == OK and "NOT" not in row.detail


def test_project_without_devorch_files(project):
    (row,) = by_name(run_checks(cwd=project), "Project settings/hooks")
    assert row.status == INFO


def test_project_instructions_detected(project):
    (project / "CLAUDE.md").write_text("rules")
    (row,) = by_name(run_checks(cwd=project), "Project instructions")
    assert row.status == OK and "CLAUDE.md" in row.detail


def test_a_crashing_check_becomes_a_failed_row_and_the_rest_still_run(monkeypatch):
    def boom(cwd):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(doctor, "check_git", boom)
    rows = run_checks()
    (git,) = [r for r in rows if r.name == "git"]
    assert git.status == FAIL and "kaboom" in git.detail and "RuntimeError" in git.detail
    assert by_name(rows, "Python") and by_name(rows, "Terminal")  # the report continued
    assert exit_code(rows) == 1


def test_git_row(project, monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    (row,) = doctor.check_git(project)
    assert row.status == WARN and "not installed" in row.detail


def test_non_utf8_terminal_is_a_warning(monkeypatch):
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(encoding="cp1252", isatty=lambda: False))
    rows = doctor.check_terminal()
    (enc,) = [r for r in rows if r.name == "Text encoding"]
    assert enc.status == WARN and "UTF-8" in enc.hint


def test_unwritable_config_folder_is_a_failure(monkeypatch, tmp_path):
    from config import settings as settings_mod

    folder = tmp_path / "cfg"
    folder.mkdir()
    monkeypatch.setattr(settings_mod, "CONFIG_DIR", folder)
    monkeypatch.setattr(settings_mod, "CONFIG_FILE", folder / "config.yaml")
    monkeypatch.setattr(doctor.os, "access", lambda path, mode: False)
    assert doctor.check_config_dir()[0].status == FAIL


def test_sessions_row_counts_saved_sessions():
    from core.sessions import SessionManager

    sm = SessionManager()
    sm.create_session("openai", "gpt-4o")
    sm.create_session("openai", "gpt-4o")
    (row,) = doctor.check_sessions()
    assert row.status == OK and row.detail.startswith("2 saved")


def test_doctor_command_exit_code_follows_the_checks(monkeypatch):
    runner = CliRunner()
    failing = runner.invoke(cli_main.app, ["doctor"])
    assert (
        failing.exit_code == 1
        and "DevOrch doctor" in failing.output
        and "problems" in failing.output
    )
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    passing = runner.invoke(cli_main.app, ["doctor"])
    assert passing.exit_code == 0


def test_doctor_output_is_safe_with_markup_like_text(monkeypatch, project):
    # paths and error text are shown verbatim, never parsed as rich markup
    (project / "DEVORCH.md").write_text("x")
    monkeypatch.setattr(
        doctor,
        "check_runtime",
        lambda: [
            doctor.Check("Odd [/bold] name", WARN, "detail [red]x[/red] and [/]", "hint [/dim]")
        ],
    )
    result = CliRunner().invoke(cli_main.app, ["doctor"])
    assert "Odd [/bold] name" in result.output and "detail [red]x[/red] and [/]" in result.output
    assert "hint [/dim]" in result.output
