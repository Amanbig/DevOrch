"""Tests for run_shell: timeouts must stop the whole process tree (the Windows hang)."""

import subprocess
import sys
import time

import pytest

from tools.shell import ShellTool
from utils import proc as proc_mod
from utils.proc import run_shell


def py(code: str) -> str:
    exe = f'"{sys.executable}"' if " " in sys.executable else sys.executable
    return f'{exe} -c "{code}"'


def test_captures_output_and_exit_code():
    r = run_shell(py("import sys; print('out'); sys.stderr.write('err'); sys.exit(3)"), timeout=30)
    assert r.returncode == 3 and "out" in r.stdout and "err" in r.stderr


def test_input_is_passed_on_stdin():
    r = run_shell(py("import sys; print(sys.stdin.read().upper())"), input="hello", timeout=30)
    assert "HELLO" in r.stdout


def test_runs_in_the_given_directory(tmp_path):
    r = run_shell(py("import os; print(os.getcwd())"), cwd=tmp_path, timeout=30)
    assert tmp_path.name in r.stdout


def test_utf8_output_decodes(tmp_path):
    r = run_shell(
        py("import sys; sys.stdout.buffer.write('caf\\u00e9'.encode('utf-8'))"),
        timeout=30,
        encoding="utf-8",
        errors="replace",
    )
    assert "café" in r.stdout


def test_timeout_returns_promptly_instead_of_waiting_for_the_command():
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_shell(py("import time; time.sleep(30)"), timeout=1)
    assert time.monotonic() - started < 15, "the command was not stopped by its timeout"


def test_timeout_kills_grandchildren_too(tmp_path):
    # parent.py starts child.py (which would write a marker after 2s) and then sleeps; killing only the
    # shell/parent would let the child finish and write the marker.
    marker = tmp_path / "marker.txt"
    (tmp_path / "child.py").write_text(
        f"import time\ntime.sleep(2)\nopen(r'{marker}', 'w').write('alive')\n"
    )
    (tmp_path / "parent.py").write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, 'child.py'])\n"
        "time.sleep(30)\n"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        run_shell(py("exec(open('parent.py').read())"), timeout=1, cwd=tmp_path)
    time.sleep(3.5)  # longer than the child's 2s sleep
    assert not marker.exists(), "a grandchild survived the timeout"


def test_keyboard_interrupt_kills_the_child_and_propagates(monkeypatch):
    spawned = []

    class InterruptedPopen(subprocess.Popen):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            spawned.append(self)
            self._first = True

        def communicate(self, *a, **k):
            if self._first:
                self._first = False
                raise KeyboardInterrupt
            return super().communicate(*a, **k)

    monkeypatch.setattr(proc_mod.subprocess, "Popen", InterruptedPopen)
    with pytest.raises(KeyboardInterrupt):
        run_shell(py("import time; time.sleep(30)"), timeout=60)
    assert spawned[0].poll() is not None, "the child was left running after Ctrl+C"


def test_shell_tool_reports_a_timeout_and_returns(monkeypatch):
    import tools.shell as shell_mod

    real = shell_mod.run_shell
    monkeypatch.setattr(shell_mod, "run_shell", lambda cmd, **kw: real(cmd, **{**kw, "timeout": 1}))
    started = time.monotonic()
    out = ShellTool().run({"command": py("import time; time.sleep(30)")})
    assert "timed out" in out.lower()
    assert time.monotonic() - started < 15


def test_shell_tool_still_formats_output():
    out = ShellTool().run({"command": py("print('hi')")})
    assert out.startswith("STDOUT:") and "hi" in out
