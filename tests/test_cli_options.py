"""--version, --continue, bare --resume and the entry-point argv handling."""

import re
import sys
from pathlib import Path

import pytest
import typer.main
from typer.testing import CliRunner

import devorch.cli.main as cli_main
from devorch.cli.constants import VERSION
from devorch.cli.repl_commands import PICK_SESSION

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


def _pyproject() -> str:
    return (
        Path(__file__).resolve().parents[1].joinpath("pyproject.toml").read_text(encoding="utf-8")
    )


def test_the_version_has_a_single_source():
    # a release guard: the version lives only in devorch/__init__.py; pyproject reads it from there and
    # the CLI prints it, so the "forgot to bump the second place" mistake cannot happen
    import devorch

    text = _pyproject()
    project_table = text[text.index("[project]") : text.index("[project.urls]")]
    assert re.search(r'^dynamic\s*=\s*\["version"\]', project_table, re.MULTILINE)
    assert not re.search(r"^version\s*=", project_table, re.MULTILINE), (
        "a hard-coded version is back"
    )
    assert 'path = "devorch/__init__.py"' in text
    assert re.fullmatch(r"\d+\.\d+\.\d+", devorch.__version__)
    assert VERSION == devorch.__version__


def test_the_wheel_ships_one_package_not_seven_generic_ones():
    # regression: it used to install cli, config, core, providers, schemas, tools and utils into
    # site-packages, where they can clash with other software
    assert 'packages = ["devorch"]' in _pyproject()
    root = Path(__file__).resolve().parents[1]
    top_level_packages = sorted(
        p.name for p in root.iterdir() if p.is_dir() and (p / "__init__.py").exists()
    )
    assert top_level_packages == ["devorch", "tests"], top_level_packages


def test_every_directory_in_the_package_is_an_explicit_package():
    package = Path(__file__).resolve().parents[1] / "devorch"
    missing = [
        str(d.relative_to(package.parent))
        for d in package.rglob("*")
        if d.is_dir() and d.name != "__pycache__" and not (d / "__init__.py").exists()
    ]
    assert missing == []


def test_python_dash_m_devorch_is_the_same_cli():
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-m", "devorch", "--version"], capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0 and out.stdout.strip() == f"devorch {VERSION}"


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
