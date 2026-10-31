"""Tests for the structured git tool."""

import subprocess

import pytest

from config.permissions import PermissionLevel, Permissions
from tools.git import GitTool, describe


@pytest.fixture
def repo(tmp_path):
    def g(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)

    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@example.com")
    g("config", "user.name", "T")
    g("config", "commit.gpgsign", "false")
    (tmp_path / "a.txt").write_text("one\n")
    g("add", ".")
    g("commit", "-q", "-m", "init")
    return GitTool(cwd=str(tmp_path)), tmp_path


def test_status_diff_add_commit_log(repo):
    tool, path = repo
    assert "main" in tool.run({"action": "status"})
    (path / "a.txt").write_text("one\ntwo\n")
    assert "+two" in tool.run({"action": "diff"})
    assert "(no changes)" == tool.run({"action": "diff", "staged": True})
    assert "a.txt" in tool.run({"action": "status"})
    tool.run({"action": "add", "paths": ["a.txt"]})
    assert "+two" in tool.run({"action": "diff", "staged": True})
    out = tool.run({"action": "commit", "message": 'second "quoted"; $(rm -rf /)'})
    assert not out.startswith("Error")
    log = tool.run({"action": "log", "max_count": 5})
    assert "init" in log and "second" in log
    assert "second" in tool.run({"action": "show"})


def test_branches(repo):
    tool, _ = repo
    tool.run({"action": "branch_create", "ref": "feat/x"})
    assert "feat/x" in tool.run({"action": "branch_list"})
    tool.run({"action": "switch", "ref": "feat/x"})
    assert "feat/x" in tool.run({"action": "status"})


def test_rejects_option_like_values(repo):
    tool, _ = repo
    assert tool.run({"action": "switch", "ref": "--detach"}).startswith("Error")
    assert tool.run({"action": "add", "paths": ["--all"]}).startswith("Error")
    assert tool.run({"action": "branch_create", "ref": "-D"}).startswith("Error")
    assert tool.run({"action": "branch_create", "ref": "bad name"}).startswith("Error")


def test_validation_errors(repo):
    tool, _ = repo
    assert tool.run({"action": "commit", "message": "  "}).startswith("Error")
    assert tool.run({"action": "add"}).startswith("Error")
    assert tool.run({"action": "switch"}).startswith("Error")
    assert tool.run({"action": "push"}).startswith("Error")


def test_git_failure_reported(repo):
    tool, _ = repo
    assert tool.run({"action": "switch", "ref": "nope"}).startswith("Error: git exited")
    assert tool.run({"action": "commit", "message": "nothing staged"}).startswith("Error")


def test_not_a_repo(tmp_path):
    assert GitTool(cwd=str(tmp_path)).run({"action": "status"}).startswith("Error")


def test_permissions_read_only_allowed_writes_ask():
    perms = Permissions.load()

    def level(args):
        return perms.check_permission("git", describe(args))[0]

    for action in ("status", "diff", "log", "show", "branch_list"):
        assert level({"action": action}) == PermissionLevel.ALLOW
    assert level({"action": "branch_create", "ref": "x"}) == PermissionLevel.ASK
    assert level({"action": "switch", "ref": "x"}) == PermissionLevel.ASK
    assert level({"action": "add", "paths": ["."]}) == PermissionLevel.ASK
    assert level({"action": "commit", "message": "git status"}) == PermissionLevel.ASK
