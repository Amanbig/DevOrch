"""Static checks for install.ps1 and for the README's install instructions (run on every OS)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
SH = (ROOT / "install.sh").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
RAW = "https://raw.githubusercontent.com/Amanbig/DevOrch/main"


def test_powershell_dies_with_throw_not_exit():
    # `exit` inside a script run through `irm | iex` would close the user's own PowerShell window
    code = "\n".join(line for line in PS1.splitlines() if not line.lstrip().startswith("#"))
    assert re.search(r"function Die\(\$Text\) \{ throw ", code)
    assert not re.search(r"(?m)^\s*exit\b", code), "a bare `exit` crept in"
    assert "; exit " not in code


def test_neither_installer_asks_for_elevated_rights():
    for text in (PS1, SH):
        lowered = text.lower()
        assert "runas" not in lowered and "-verb" not in lowered
    assert not re.search(r"(?m)^\s*(\+ )?sudo\b", SH)


def test_both_installers_support_the_same_options():
    for sh_flag, ps_param in [
        ("--version", "$Version"),
        ("--method", "$Method"),
        ("--from", "$From"),
        ("--yes", "$Yes"),
        ("--dry-run", "$DryRun"),
        ("--uninstall", "$Uninstall"),
    ]:
        assert sh_flag in SH and ps_param in PS1, (sh_flag, ps_param)


def test_both_installers_read_the_same_environment_variables():
    for var in (
        "DEVORCH_VERSION",
        "DEVORCH_METHOD",
        "DEVORCH_FROM",
        "DEVORCH_YES",
        "DEVORCH_BIN_DIR",
    ):
        assert var in SH and var in PS1, var


def test_both_installers_leave_user_data_alone():
    assert "~/.devorch were kept" in SH
    assert "were kept" in PS1
    # nothing the installers actually delete may be the user's ~/.devorch (only the message mentions it)
    removals = [
        line
        for line in PS1.splitlines()
        if "Remove-Item" in line and not line.lstrip().startswith(("Say", "#"))
    ]
    assert removals and not any(".devorch" in line for line in removals)
    deletions = [
        line for line in SH.splitlines() if re.search(r"\brm\b", line) and "say " not in line
    ]
    assert deletions and not any(".devorch" in line for line in deletions)


def test_the_installers_do_not_edit_shell_profiles_when_bootstrapping_uv():
    assert "UV_NO_MODIFY_PATH=1" in SH
    assert "UV_NO_MODIFY_PATH" in PS1


def test_the_installer_script_is_executable():
    import os

    if os.name != "nt":
        assert os.access(ROOT / "install.sh", os.X_OK)


def test_readme_documents_both_installers_with_the_real_urls():
    assert f"curl -fsSL {RAW}/install.sh | sh" in README
    assert f"irm {RAW}/install.ps1 | iex" in README
    for needle in ("--uninstall", "-Uninstall", "--dry-run", "--version 0.5.2"):
        assert needle in README, needle


def test_readme_still_lists_the_package_manager_routes():
    assert "pipx install devorch" in README and "uv tool install devorch" in README
