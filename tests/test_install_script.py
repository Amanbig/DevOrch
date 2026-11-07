"""Hermetic tests for install.sh: every decision branch, using stub uv/pipx/python3/curl on a controlled PATH.

The stubs only log what they were asked to run (and create a fake `devorch` the script can verify), so no
network or real installation is involved. Real end-to-end installs run in CI and in Docker.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "install.sh"
SH = shutil.which("sh")

pytestmark = pytest.mark.skipif(
    os.name == "nt" or SH is None, reason="install.sh targets Linux and macOS"
)

# what install.sh itself uses, plus cp/chmod which only the stub tools need
CORE_TOOLS = [
    "sh",
    "uname",
    "cat",
    "sed",
    "grep",
    "mkdir",
    "ln",
    "rm",
    "readlink",
    "env",
    "cp",
    "chmod",
]

FAKE_DEVORCH = '#!/bin/sh\n[ "${DEVORCH_STUB_FAIL:-0}" = 1 ] && exit 1\necho "devorch 9.9.9"\n'


def write_exe(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class Sandbox:
    """A throwaway HOME and a PATH containing only the tools a scenario wants to exist."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.home = tmp / "home"
        self.home.mkdir()
        self.core = tmp / "core"
        self.stubs = tmp / "stubs"
        self.log = tmp / "calls.log"
        self.log.write_text("")
        self.uv_bin = tmp / "uvbin"
        self.pipx_bin = tmp / "pipxbin"
        self.core.mkdir()
        self.stubs.mkdir()
        for name in CORE_TOOLS:
            real = shutil.which(name)
            if real:
                (self.core / name).symlink_to(real)
        self.extra_path: list[Path] = []
        self.env_extra: dict[str, str] = {}

    # ── stub tools ──
    def add_uv(self, installed: bool = False) -> None:
        write_exe(
            self.stubs / "uv",
            f"""#!/bin/sh
echo "uv $*" >> "{self.log}"
case "$*" in
  "tool dir --bin") echo "{self.uv_bin}" ;;
  "tool list") {'echo "devorch v9.9.9"' if installed else ":"} ;;
  "tool install"*) mkdir -p "{self.uv_bin}"; cp "{self.tmp}/fake_devorch" "{self.uv_bin}/devorch" ;;
esac
""",
        )
        write_exe(self.tmp / "fake_devorch", FAKE_DEVORCH)

    def add_pipx(self, installed: bool = False) -> None:
        write_exe(
            self.stubs / "pipx",
            f"""#!/bin/sh
echo "pipx $*" >> "{self.log}"
case "$*" in
  "environment --value PIPX_BIN_DIR") echo "{self.pipx_bin}" ;;
  "list --short") {'echo "devorch 9.9.9"' if installed else ":"} ;;
  "install"*) mkdir -p "{self.pipx_bin}"; cp "{self.tmp}/fake_devorch" "{self.pipx_bin}/devorch" ;;
esac
""",
        )
        write_exe(self.tmp / "fake_devorch", FAKE_DEVORCH)

    def add_python(self, ok: bool = True, venv: bool = True, name: str = "python3") -> None:
        write_exe(self.tmp / "fake_devorch", FAKE_DEVORCH)
        write_exe(
            self.stubs / name,
            f"""#!/bin/sh
echo "{name} $*" >> "{self.log}"
case "$*" in
  *sys.version_info*) exit {0 if ok else 1} ;;
  *ensurepip*) exit {0 if venv else 1} ;;
  "-m venv "*)
    dir="$3"; mkdir -p "$dir/bin"
    cp "{self.tmp}/fake_devorch" "$dir/bin/devorch"
    cat > "$dir/bin/python" <<'PYEOF'
#!/bin/sh
echo "venv-python $*" >> "{self.log}"
PYEOF
    chmod +x "$dir/bin/python" ;;
esac
""",
        )

    def add_curl(self, uv_installer_creates_uv: bool = True) -> None:
        """A curl that serves a fake astral installer, which drops a stub uv into $HOME/.local/bin."""
        write_exe(self.tmp / "fake_devorch", FAKE_DEVORCH)
        uv_script = (
            f"""#!/bin/sh
echo "uv $*" >> "{self.log}"
case "$*" in
  "tool dir --bin") echo "{self.uv_bin}" ;;
  "tool install"*) mkdir -p "{self.uv_bin}"; cp "{self.tmp}/fake_devorch" "{self.uv_bin}/devorch" ;;
esac
"""
            if uv_installer_creates_uv
            else ""
        )
        write_exe(
            self.stubs / "curl",
            f"""#!/bin/sh
echo "curl $*" >> "{self.log}"
cat <<'INSTALLER'
echo "astral-installer ran (UV_NO_MODIFY_PATH=$UV_NO_MODIFY_PATH)" >> "{self.log}"
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/uv" <<'UVEOF'
{uv_script}UVEOF
chmod +x "$HOME/.local/bin/uv"
INSTALLER
""",
        )

    def fake_uname(self, system: str) -> None:
        write_exe(self.stubs / "uname", f'#!/bin/sh\necho "{system}"\n')

    # ── running ──
    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        path = ":".join([str(self.stubs), *map(str, self.extra_path), str(self.core)])
        full_env = {
            "PATH": path,
            "HOME": str(self.home),
            "STUB_LOG": str(self.log),
            **self.env_extra,
            **env,
        }
        return subprocess.run(
            [str(self.core / "sh"), str(SCRIPT), *args],
            env=full_env,
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
            # no controlling terminal: otherwise, run from a developer's terminal, the script would
            # prompt on the real /dev/tty and the test would hang waiting for an answer
            start_new_session=True,
        )

    @property
    def calls(self) -> list[str]:
        return [line for line in self.log.read_text().splitlines() if line]


@pytest.fixture
def box(tmp_path):
    return Sandbox(tmp_path)


def combined(result) -> str:
    return result.stdout + result.stderr


# ── help and argument handling ──────────────────────────────────────────────


def test_help_is_embedded_and_exits_zero(box):
    r = box.run("--help")
    assert r.returncode == 0 and "Usage:" in r.stdout and "--uninstall" in r.stdout
    assert box.calls == []


def test_help_works_when_piped_like_curl_sh(box):
    # when run as `curl ... | sh`, $0 is "sh", so help must not depend on reading the script file
    r = subprocess.run(
        [str(box.core / "sh"), "-s", "--", "--help"],
        input=SCRIPT.read_text(),
        env={"PATH": str(box.core), "HOME": str(box.home)},
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0 and "Usage:" in r.stdout


def test_unknown_option_is_rejected_with_usage(box):
    r = box.run("--frobnicate")
    assert r.returncode == 2 and "unknown option" in r.stderr and "Usage:" in r.stderr


@pytest.mark.parametrize("flag", ["--version", "--method", "--from", "--bin-dir"])
def test_options_that_need_a_value_say_so(box, flag):
    r = box.run(flag)
    assert r.returncode != 0 and "needs a value" in r.stderr


def test_invalid_method_is_rejected(box):
    r = box.run("--method", "magic")
    assert r.returncode != 0 and "must be one of" in r.stderr


def test_windows_shells_are_pointed_to_the_powershell_installer(box):
    box.fake_uname("MINGW64_NT-10.0")
    r = box.run()
    assert r.returncode != 0 and "install.ps1" in r.stderr


def test_unsupported_os_is_refused(box):
    box.fake_uname("FreeBSD")
    r = box.run()
    assert r.returncode != 0 and "unsupported operating system" in r.stderr


# ── choosing an installer ───────────────────────────────────────────────────


def test_uv_is_preferred_when_everything_exists(box):
    box.add_uv()
    box.add_pipx()
    box.add_python()
    r = box.run()
    assert r.returncode == 0, combined(r)
    assert "uv tool install --force devorch" in box.calls
    assert not any(c.startswith(("pipx install", "python3 -m venv")) for c in box.calls)
    assert "Installed: devorch 9.9.9" in r.stdout


def test_pipx_is_used_when_there_is_no_uv(box):
    box.add_pipx()
    box.add_python()
    r = box.run()
    assert r.returncode == 0, combined(r)
    assert "pipx install --force devorch" in box.calls
    assert not any("venv" in c for c in box.calls)


def test_a_private_venv_is_the_fallback(box):
    box.add_python()
    r = box.run()
    assert r.returncode == 0, combined(r)
    venv = box.home / ".local" / "share" / "devorch" / "venv"
    assert f"python3 -m venv {venv}" in box.calls
    assert any(c.startswith("venv-python -m pip install --upgrade devorch") for c in box.calls)
    link = box.home / ".local" / "bin" / "devorch"
    assert link.is_symlink() and os.readlink(link) == str(venv / "bin" / "devorch")


def test_venv_install_is_idempotent(box):
    box.add_python()
    box.run()
    first = len([c for c in box.calls if " -m venv " in c])
    r = box.run()
    assert r.returncode == 0, combined(r)
    assert len([c for c in box.calls if " -m venv " in c]) == first  # reused, not recreated


def test_a_python_without_the_venv_module_is_not_used(box):
    # Debian/Ubuntu ship python3 without venv until python3-venv is installed
    box.add_python(venv=False)
    r = box.run()
    assert r.returncode != 0
    assert not any(" -m venv " in c for c in box.calls)


def test_too_old_a_python_is_not_used(box):
    box.add_python(ok=False)
    r = box.run()
    assert r.returncode != 0 and not any(" -m venv " in c for c in box.calls)


def test_versioned_python_names_are_found(box):
    box.add_python(name="python3.12")
    r = box.run()
    assert r.returncode == 0, combined(r)
    assert any(c.startswith("python3.12 -m venv") for c in box.calls)


# ── bootstrapping uv ────────────────────────────────────────────────────────


def test_without_any_installer_it_asks_and_does_nothing_when_non_interactive(box):
    box.add_curl()
    r = box.run()  # stdin is /dev/null and there is no tty: it cannot ask, so it must not proceed
    assert r.returncode != 0 and "--yes" in r.stderr
    assert not any(c.startswith("curl") for c in box.calls)


def test_no_terminal_means_a_quiet_refusal_not_dev_tty_errors(box):
    # in containers and CI /dev/tty exists as a file with no terminal behind it
    box.add_curl()
    r = box.run()
    assert r.returncode != 0
    assert (
        "/dev/tty" not in r.stderr
        and "cannot create" not in r.stderr
        and "cannot open" not in r.stderr
    )
    assert "--yes" in r.stderr


def test_yes_lets_it_bootstrap_uv_and_then_use_it(box):
    box.add_curl()
    r = box.run("--yes")
    assert r.returncode == 0, combined(r)
    assert any("astral.sh/uv/install.sh" in c for c in box.calls if c.startswith("curl"))
    assert (
        "astral-installer ran (UV_NO_MODIFY_PATH=1)" in box.calls
    )  # shell profiles are left alone
    assert "uv tool install --force devorch" in box.calls
    assert "Installed: devorch 9.9.9" in r.stdout


def test_yes_via_environment_variable(box):
    box.add_curl()
    r = box.run(DEVORCH_YES="1")
    assert r.returncode == 0, combined(r)


def test_bootstrapping_needs_curl_or_wget(box):
    r = box.run("--yes")
    assert r.returncode != 0 and "curl or wget" in r.stderr


# ── explicit method, version, source ────────────────────────────────────────


@pytest.mark.parametrize("method", ["uv", "pipx"])
def test_a_forced_method_that_is_missing_is_an_error_not_a_fallback(box, method):
    box.add_python()
    r = box.run("--method", method)
    assert r.returncode != 0 and f"--method {method}" in r.stderr
    assert not any(" -m venv " in c for c in box.calls)


def test_forced_venv_method_even_when_uv_exists(box):
    box.add_uv()
    box.add_python()
    r = box.run("--method", "venv")
    assert r.returncode == 0, combined(r)
    assert not any(c.startswith("uv tool install") for c in box.calls)


def test_version_pin(box):
    box.add_uv()
    assert box.run("--version", "1.2.3").returncode == 0
    assert "uv tool install --force devorch==1.2.3" in box.calls


def test_version_pin_equals_form_and_environment(box):
    box.add_uv()
    box.run("--version=4.5.6")
    box.run(DEVORCH_VERSION="7.8.9")
    assert "uv tool install --force devorch==4.5.6" in box.calls
    assert "uv tool install --force devorch==7.8.9" in box.calls


def test_install_from_a_local_wheel(box):
    box.add_uv()
    assert box.run("--from", "/builds/devorch-1.0-py3-none-any.whl").returncode == 0
    assert "uv tool install --force /builds/devorch-1.0-py3-none-any.whl" in box.calls


def test_a_path_with_spaces_stays_one_argument(box):
    box.add_uv()
    box.run("--from", "/my builds/devorch.whl")
    assert "uv tool install --force /my builds/devorch.whl" in box.calls


def test_custom_bin_dir_for_the_venv_method(box, tmp_path):
    box.add_python()
    target = tmp_path / "mybin"
    r = box.run("--bin-dir", str(target))
    assert r.returncode == 0, combined(r)
    assert (target / "devorch").is_symlink()


# ── dry run ─────────────────────────────────────────────────────────────────


def test_dry_run_prints_the_plan_and_changes_nothing(box):
    box.add_python()
    r = box.run("--dry-run")
    assert r.returncode == 0, combined(r)
    assert "+ " in r.stdout and "Dry run: nothing was changed" in r.stdout
    assert not (box.home / ".local").exists()
    assert not any(" -m venv " in c or "pip install" in c for c in box.calls)  # detection only


def test_dry_run_with_uv_runs_no_install(box):
    box.add_uv()
    r = box.run("--dry-run", "--version", "2.0.0")
    assert r.returncode == 0 and "+ uv tool install --force devorch==2.0.0" in r.stdout
    assert not any(c.startswith("uv tool install") for c in box.calls)


# ── after the install ───────────────────────────────────────────────────────


def test_path_advice_when_the_bin_dir_is_not_on_path(box):
    box.add_uv()
    r = box.run()
    assert "is not on your PATH" in r.stderr and "export PATH=" in r.stdout


def test_no_path_advice_when_it_already_is(box):
    box.add_uv()
    box.extra_path.append(box.uv_bin)
    r = box.run()
    assert "is not on your PATH" not in r.stderr


def test_a_broken_install_is_reported_not_celebrated(box):
    box.add_uv()
    r = box.run(DEVORCH_STUB_FAIL="1")
    assert r.returncode != 0 and "--version' failed" in r.stderr
    assert "Installed:" not in r.stdout


def test_it_never_uses_sudo(box):
    assert "sudo" not in SCRIPT.read_text().replace("never uses sudo", "").replace(
        "never use sudo", ""
    )


# ── uninstall ───────────────────────────────────────────────────────────────


def test_uninstall_uv(box):
    box.add_uv(installed=True)
    r = box.run("--uninstall")
    assert r.returncode == 0, combined(r)
    assert "uv tool uninstall devorch" in box.calls and "~/.devorch were kept" in r.stdout


def test_uninstall_pipx(box):
    box.add_pipx(installed=True)
    r = box.run("--uninstall")
    assert r.returncode == 0, combined(r)
    assert "pipx uninstall devorch" in box.calls


def test_uninstall_removes_the_venv_and_its_link_but_not_user_data(box):
    box.add_python()
    box.run()
    devorch_home = box.home / ".devorch"
    devorch_home.mkdir()
    (devorch_home / "config.yaml").write_text("keep me")
    r = box.run("--uninstall")
    assert r.returncode == 0, combined(r)
    assert not (box.home / ".local" / "share" / "devorch" / "venv").exists()
    assert not (box.home / ".local" / "bin" / "devorch").exists()
    assert (devorch_home / "config.yaml").read_text() == "keep me"


def test_uninstall_leaves_an_unrelated_devorch_link_alone(box):
    box.add_python()
    box.run()
    link = box.home / ".local" / "bin" / "devorch"
    link.unlink()
    other = box.tmp / "somewhere_else"
    write_exe(other, "#!/bin/sh\n")
    link.symlink_to(other)  # a devorch the user installed some other way
    box.run("--uninstall")
    assert link.is_symlink() and os.readlink(link) == str(other)


def test_uninstall_when_nothing_is_installed(box):
    r = box.run("--uninstall")
    assert r.returncode == 0 and "nothing to remove" in r.stdout
