"""Run shell commands with a timeout that really stops them.

``subprocess.run(cmd, shell=True, timeout=...)`` only kills the *shell*. On Windows the command's own
process keeps running and keeps the output pipes open, so ``run`` blocks until it exits anyway (a
30-second sleep with a 1-second timeout took 30 seconds). On POSIX the same happens whenever the shell
does not exec its last command. This helper starts the command in its own process group / session and
kills the whole tree on timeout or on Ctrl+C.
"""

import os
import signal
import subprocess
from typing import Any

REAP_TIMEOUT = 5  # seconds to wait for pipes to close after the tree has been killed


def kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill ``proc`` and everything it started."""
    try:
        if os.name == "nt":
            # /T = the whole tree, /F = force. taskkill ships with every Windows install.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
                timeout=REAP_TIMEOUT,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)  # the group id equals the pid (new session)
    except (ProcessLookupError, PermissionError, OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()  # belt and braces, e.g. if taskkill was unavailable
    except OSError:
        pass


def run_shell(
    command: str,
    *,
    input: str | None = None,
    timeout: float | None = None,
    cwd: Any = None,
    encoding: str | None = None,
    errors: str | None = None,
) -> subprocess.CompletedProcess:
    """``subprocess.run(command, shell=True, capture_output=True, text=True)`` that kills the whole
    process tree on timeout or interrupt. Raises ``subprocess.TimeoutExpired`` like ``run`` does.

    stdin is inherited unless ``input`` is given, matching ``subprocess.run``.
    """
    extra: dict[str, Any] = {}
    if os.name != "nt":
        extra["start_new_session"] = True
    proc = subprocess.Popen(
        command,
        shell=True,
        stdin=subprocess.PIPE if input is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding=encoding,
        errors=errors,
        cwd=cwd,
        **extra,
    )
    try:
        stdout, stderr = proc.communicate(input=input, timeout=timeout)
    except BaseException:  # TimeoutExpired, KeyboardInterrupt, ...
        kill_process_tree(proc)
        try:
            proc.communicate(timeout=REAP_TIMEOUT)
        except Exception:
            pass
        raise
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
