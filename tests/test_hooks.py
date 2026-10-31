"""Tests for the hooks system."""

import json
import sys
from pathlib import Path

from core.executor import ToolExecutor
from core.hooks import POST_TOOL_USE, PRE_TOOL_USE, Hook, HookManager, _load_file
from tools.base import Tool


class EchoTool(Tool):
    name = "echo"
    description = "echo"

    def run(self, arguments):
        return "ran"


def _executor(hooks):
    return ToolExecutor([EchoTool()], require_confirmation=False, hooks=hooks)


def test_matcher():
    assert Hook("x", matcher="shell|edit").matches("edit")
    assert not Hook("x", matcher="shell").matches("shell2")
    assert Hook("x").matches("anything")


def test_pre_hook_blocks_with_exit_2():
    h = HookManager({PRE_TOOL_USE: [Hook("echo nope >&2; exit 2")]})
    out = _executor(h).execute("echo", {})
    assert "Blocked by PreToolUse hook" in out and "nope" in out


def test_pre_hook_nonblocking_error_allows():
    h = HookManager({PRE_TOOL_USE: [Hook("exit 1")]})
    assert _executor(h).execute("echo", {}) == "ran"


def test_post_hook_feedback_appended():
    h = HookManager({POST_TOOL_USE: [Hook("echo lint failed >&2; exit 2")]})
    out = _executor(h).execute("echo", {})
    assert out.startswith("ran") and "lint failed" in out


def test_hook_receives_json_payload(tmp_path):
    dump = tmp_path / "payload.json"
    cmd = f"{sys.executable} -c \"import sys; open(r'{dump}','w').write(sys.stdin.read())\""
    h = HookManager({POST_TOOL_USE: [Hook(cmd)]}, cwd=tmp_path)
    _executor(h).execute("echo", {"a": 1})
    data = json.loads(dump.read_text())
    assert data["event"] == POST_TOOL_USE
    assert data["tool_name"] == "echo"
    assert data["tool_input"] == {"a": 1}
    assert data["tool_output"] == "ran"


def test_timeout_does_not_block():
    h = HookManager({PRE_TOOL_USE: [Hook("sleep 5", timeout=1)]})
    assert _executor(h).execute("echo", {}) == "ran"


def test_load_file(tmp_path: Path):
    f = tmp_path / "hooks.yaml"
    f.write_text(
        "hooks:\n  PreToolUse:\n    - matcher: shell\n      command: ./c.sh\n      timeout: 5\n"
        "  Bogus:\n    - command: x\n  PostToolUse:\n    - nocommand: true\n"
    )
    loaded = _load_file(f)
    assert list(loaded) == [PRE_TOOL_USE]
    assert loaded[PRE_TOOL_USE][0].timeout == 5


def test_load_merges_project_hooks(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    proj = tmp_path / "proj" / ".devorch"
    proj.mkdir(parents=True)
    (proj / "hooks.yaml").write_text("hooks:\n  PostToolUse:\n    - command: echo hi\n")
    mgr = HookManager.load(tmp_path / "proj")
    assert mgr.has_hooks()
