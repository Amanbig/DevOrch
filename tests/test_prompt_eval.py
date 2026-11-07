"""Tests for scripts/prompt_eval.py (the scenario runner), using synthetic agent results."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prompt_eval.py"
spec = importlib.util.spec_from_file_location("prompt_eval", SCRIPT)
pe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pe)


def call(name, **arguments):
    return {"name": name, "arguments": arguments, "is_error": False, "output": ""}


def result(text="An answer.", *calls, error=None):
    return {
        "is_error": error is not None,
        "error": error,
        "result": None if error else text,
        "tool_calls": list(calls),
    }


def by_name(name):
    return next(s for s in pe.SCENARIOS if s.name == name)


# ── what counts as changing something ───────────────────────────────────────


@pytest.mark.parametrize(
    "c",
    [
        call("edit", action="replace", path="a.py"),
        call("filesystem", action="write", path="a.py"),
        call("git", action="commit", message="x"),
        call("git", action="add", paths=["."]),
        call("shell", command="pip install pytest"),
        call("shell", command="python -m venv venv && . venv/bin/activate"),
        call("shell", command="rm -rf build"),
        call("shell", command="echo hi > out.txt"),
        call("shell", command="sed -i 's/a/b/' x.py"),
        call("shell", command="uv pip install -e ."),
        call("shell", command="git checkout main"),
        call("terminal_session", action="start", command="npm run dev"),
    ],
)
def test_state_changing_calls_are_recognised(c):
    assert pe.is_modifying(c)


@pytest.mark.parametrize(
    "c",
    [
        call("filesystem", action="read", path="a.py"),
        call("filesystem", action="list", path="."),
        call("edit", action="replace", path="a.py", dry_run=True),
        call("git", action="diff"),
        call("git", action="status"),
        call("search", pattern="*.py"),
        call("grep", pattern="x"),
        call("shell", command="pytest -q 2>&1 | tail -5"),  # 2>&1 is not a redirect to a file
        call("shell", command="cat math_utils.py"),
        call("shell", command="git log --oneline -3"),
        call("memory", action="search", query="x"),
        call("terminal_session", action="read", session_id="s"),
    ],
)
def test_read_only_calls_are_not_flagged(c):
    assert not pe.is_modifying(c)


# ── scenario checks ─────────────────────────────────────────────────────────


def test_question_passes_when_only_reading():
    ok = result(
        "Add a docstring and type hints.", call("filesystem", action="read", path="math_utils.py")
    )
    assert by_name("question_no_changes").check(ok, {}) == []


def test_question_fails_if_it_edits_or_installs():
    sc = by_name("question_no_changes")
    for bad in (
        call("edit", action="replace", path="math_utils.py"),
        call("shell", command="pip install ruff"),
        call("filesystem", action="write", path="new.py"),
    ):
        problems = sc.check(result("I improved it.", bad), {})
        assert any("changed something" in p for p in problems), bad


def test_every_scenario_fails_a_failed_run_or_an_empty_answer():
    for sc in pe.SCENARIOS:
        assert any("failed" in p for p in sc.check(result(error="boom"), {"workdir": None}))
        assert any("no final answer" in p for p in sc.check(result("   "), {"workdir": None}))


def test_run_tests_scenario():
    sc = by_name("run_tests_uses_shell")
    assert sc.check(result("2 passed", call("shell", command="pytest")), {}) == []
    assert any("never ran" in p for p in sc.check(result("They pass."), {}))
    gui = result("done", call("terminal_session", action="start", command="pytest", gui=True))
    problems = sc.check(gui, {})
    assert any("terminal_session" in p for p in problems) and any(
        "never ran" in p for p in problems
    )


def test_reads_before_answering_scenario():
    sc = by_name("reads_before_answering")
    good = result(
        "It returns the sum of a and b.",
        call("filesystem", action="read", path="/tmp/x/math_utils.py"),
    )
    assert sc.check(good, {}) == []
    guessed = result("It returns the sum of a and b.")
    assert any("without opening" in p for p in sc.check(guessed, {}))
    vague = result("Not sure.", call("grep", pattern="def add", path="math_utils.py"))
    assert any("does not mention" in p for p in sc.check(vague, {}))


def test_fix_request_scenario(tmp_path):
    sc = by_name("fix_request_edits")
    pe.build_fixture(tmp_path)
    edit = call("edit", action="replace", path="math_utils.py", find="a + b", replace_with="a - b")
    # claims success but the file is unchanged
    problems = sc.check(result("Fixed.", edit), {"workdir": tmp_path})
    assert problems == ["math_utils.py still does not subtract"]
    # actually fixed
    (tmp_path / "math_utils.py").write_text("def subtract(a, b):\n    return a - b\n")
    assert sc.check(result("Fixed.", edit), {"workdir": tmp_path}) == []
    # over-cautious: no change at all
    problems = sc.check(result("You could change it."), {"workdir": tmp_path})
    assert any("never changed" in p for p in problems)


# ── plumbing ────────────────────────────────────────────────────────────────


def test_scenario_names_are_unique_and_described():
    names = [s.name for s in pe.SCENARIOS]
    assert len(names) == len(set(names)) and all(s.what and s.prompt for s in pe.SCENARIOS)


def test_fixture_has_the_bug_and_a_failing_test(tmp_path):
    pe.build_fixture(tmp_path)
    assert "return a + b" in (tmp_path / "math_utils.py").read_text().split("def subtract")[1]
    assert "def test_subtract" in (tmp_path / "test_math_utils.py").read_text()


def test_parse_result_takes_the_json_line():
    out = "some banner\n" + json.dumps({"type": "result", "result": "hi"}) + "\n"
    assert pe.parse_result(out)["result"] == "hi"
    assert pe.parse_result("no json here") is None
    assert pe.parse_result('{"broken": \n') is None


def test_command_line():
    cmd = pe.command_for("do it", "openai", "gpt-4o")
    assert (
        cmd[-1] == "do it"
        and cmd[cmd.index("-p") + 1] == "openai"
        and cmd[cmd.index("-m") + 1] == "gpt-4o"
    )
    assert "--output" in cmd and "json" in cmd and cmd[cmd.index("--mode") + 1] == "auto"
    bare = pe.command_for("x", None, None)
    assert "-p" not in bare and "-m" not in bare


def test_run_scenario_cleans_up_and_reports(monkeypatch):
    seen = {}

    def fake_run(cmd, cwd, **kw):
        seen["cwd"] = Path(cwd)
        assert (Path(cwd) / "math_utils.py").exists()  # the fixture exists while running
        payload = result("2 passed", call("shell", command="pytest"))
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload) + "\n", stderr="")

    monkeypatch.setattr(pe.subprocess, "run", fake_run)
    passed, reasons = pe.run_scenario(by_name("run_tests_uses_shell"), None, None, timeout=5)
    assert passed and reasons == []
    assert not seen["cwd"].exists()  # temp project removed


def test_run_scenario_keep_leaves_the_files(monkeypatch, capsys):
    def fake_run(cmd, cwd, **kw):
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(result("x", call("shell", command="pytest"))), stderr=""
        )

    monkeypatch.setattr(pe.subprocess, "run", fake_run)
    pe.run_scenario(by_name("run_tests_uses_shell"), None, None, timeout=5, keep=True)
    kept = Path(capsys.readouterr().out.split("files kept in ")[1].strip())
    try:
        assert (kept / "math_utils.py").exists()
    finally:
        import shutil

        shutil.rmtree(kept, ignore_errors=True)


def test_run_scenario_handles_timeouts_and_garbage(monkeypatch):
    def timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(pe.subprocess, "run", timeout)
    passed, reasons = pe.run_scenario(by_name("run_tests_uses_shell"), None, None, timeout=1)
    assert not passed and "timed out" in reasons[0]

    def garbage(cmd, **kw):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="Error: No API key found\nmore"
        )

    monkeypatch.setattr(pe.subprocess, "run", garbage)
    passed, reasons = pe.run_scenario(by_name("run_tests_uses_shell"), None, None, timeout=1)
    assert not passed and reasons[0] == "no JSON result" and "No API key" in " ".join(reasons)


def test_main_list_and_exit_codes(monkeypatch, capsys):
    assert pe.main(["--list"]) == 0
    assert "question_no_changes" in capsys.readouterr().out
    assert pe.main(["--only", "nope"]) == 2
    monkeypatch.setattr(pe, "run_scenario", lambda *a, **k: (True, []))
    assert pe.main(["--only", "run_tests_uses_shell"]) == 0
    assert "1/1 scenarios passed" in capsys.readouterr().out
    monkeypatch.setattr(pe, "run_scenario", lambda *a, **k: (False, ["because"]))
    assert pe.main(["--only", "run_tests_uses_shell", "fix_request_edits"]) == 1
    out = capsys.readouterr().out
    assert "FAIL  run_tests_uses_shell" in out and "because" in out and "0/2" in out
