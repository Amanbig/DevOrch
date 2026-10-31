"""--version, --continue, bare --resume and the entry-point argv handling."""

import re
import sys
from pathlib import Path

import pytest
import typer.main
from typer.testing import CliRunner

import cli.main as cli_main
from cli.constants import VERSION
from cli.repl_commands import PICK_SESSION

normalize = cli_main.normalize_resume_argv


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], []),
        (["--resume"], ["--resume", PICK_SESSION]),
        (["-r"], ["-r", PICK_SESSION]),
        (["--resume", "abc123"], ["--resume", "abc123"]),
        (["-r", "abc123"], ["-r", "abc123"]),
        (["--resume=abc123"], ["--resume=abc123"]),
        (["--resume", "-c"], ["--resume", PICK_SESSION, "-c"]),
        (["-r", "--mode", "plan"], ["-r", PICK_SESSION, "--mode", "plan"]),
        (["-p", "openai", "--resume"], ["-p", "openai", "--resume", PICK_SESSION]),
        (["--continue"], ["--continue"]),
        (["ask", "hello"], ["ask", "hello"]),
        (["--resume", "--resume"], ["--resume", PICK_SESSION, "--resume", PICK_SESSION]),
    ],
)
def test_bare_resume_becomes_the_picker_marker(argv, expected):
    assert normalize(argv) == expected


def test_normalizing_does_not_mutate_its_input():
    argv = ["--resume"]
    normalize(argv)
    assert argv == ["--resume"]


def test_entry_point_passes_the_normalized_arguments(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli_main, "app", lambda args=None: captured.update(args=args))
    monkeypatch.setattr(sys, "argv", ["devorch", "--resume"])
    cli_main.main()
    assert captured["args"] == ["--resume", PICK_SESSION]


def test_version_flag_prints_and_exits_without_starting_anything():
    runner = CliRunner()
    for flag in ("--version", "-V"):
        result = runner.invoke(cli_main.app, [flag])
        assert result.exit_code == 0 and result.output.strip() == f"devorch {VERSION}"


def test_version_matches_pyproject():
    # a release guard: the version is declared in two places and they must agree
    text = (
        Path(__file__).resolve().parents[1].joinpath("pyproject.toml").read_text(encoding="utf-8")
    )
    declared = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE).group(1)
    assert declared == VERSION


def test_continue_and_resume_are_options_of_the_repl_entry_points():
    root = typer.main.get_command(cli_main.app)
    for name, command in {"devorch": root, "chat": root.commands["chat"]}.items():
        opts = {o for p in command.params for o in getattr(p, "opts", [])}
        assert {"--continue", "-c", "--resume", "-r"} <= opts, name
    assert "--version" in {o for p in root.params for o in getattr(p, "opts", [])}


def test_doctor_is_a_command():
    assert "doctor" in typer.main.get_command(cli_main.app).commands


def test_sessions_list_has_a_here_option():
    sessions = typer.main.get_command(cli_main.app).commands["sessions"]
    opts = {o for p in sessions.commands["list"].params for o in getattr(p, "opts", [])}
    assert "--here" in opts
