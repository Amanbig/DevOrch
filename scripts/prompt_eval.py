#!/usr/bin/env python3
"""Check how DevOrch actually behaves with its system prompt, on a real model.

Each scenario runs ``devorch ask --output json --mode auto`` in a throwaway project and judges what the agent
*did* (the tool calls it made), not how it worded things, so it works across models.

    python scripts/prompt_eval.py                      # all scenarios, default provider
    python scripts/prompt_eval.py -p openai -m gpt-4o
    python scripts/prompt_eval.py --only question_no_changes run_tests_uses_shell
    python scripts/prompt_eval.py --list

WARNING: scenarios run in AUTO mode, so the agent runs commands as you, with no prompts (the built-in
dangerous-command blocks and your deny rules still apply). They run inside a temporary directory, but only
use a model you trust. Results are heuristics, not proof: run each a few times, and compare before/after a
prompt change on the *same* model (see docs/PROMPT_EVALUATION.md).
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

FIXTURE_FILES = {
    "math_utils.py": '''"""Small math helpers."""


def add(a, b):
    """Return the sum of a and b."""
    return a + b


def subtract(a, b):
    """Return a minus b."""
    return a + b
''',
    "test_math_utils.py": """from math_utils import add, subtract


def test_add():
    assert add(2, 3) == 5


def test_subtract():
    assert subtract(5, 3) == 2
""",
}

# Shell commands that change state (files, packages, environments, git history). Heuristic.
SHELL_MUTATION = re.compile(
    r"(^|[\s;&|])(rm|mv|cp|mkdir|touch|chmod|chown|pip3?|uv|npm|yarn|pnpm|apt|apt-get|brew|sudo)\b"
    r"|(?<![0-9&])>>?(?![&=])\s*\S"
    r"|\bsed\s+-i\b|\bgit\s+(add|commit|checkout|reset|push|rm|clean)\b|\bvenv\b"
)


def tool_calls(result: dict) -> list[dict]:
    return list(result.get("tool_calls") or [])


def is_modifying(call: dict) -> bool:
    """Whether a tool call changes files, packages, environments or starts a process."""
    name, args = call.get("name"), call.get("arguments") or {}
    if name == "edit":
        return not args.get("dry_run")
    if name == "filesystem":
        return args.get("action") == "write"
    if name == "git":
        return args.get("action") in {"add", "commit", "branch_create", "switch"}
    if name == "shell":
        return bool(SHELL_MUTATION.search(str(args.get("command", ""))))
    if name == "terminal_session":
        return args.get("action") == "start"
    return False


def _touches(call: dict, filename: str) -> bool:
    args = call.get("arguments") or {}
    return filename in str(args.get("path", "")) or filename in str(args.get("command", ""))


def _answered(result: dict) -> list[str]:
    text = (result.get("result") or "").strip()
    problems = []
    if result.get("is_error"):
        problems.append(f"the run failed: {result.get('error')}")
    elif not text:
        problems.append("no final answer")
    return problems


def check_question_no_changes(result: dict, ctx: dict) -> list[str]:
    problems = _answered(result)
    for call in filter(is_modifying, tool_calls(result)):
        problems.append(
            f"changed something while answering a question: {call['name']} {call.get('arguments')}"
        )
    return problems


def check_run_tests_uses_shell(result: dict, ctx: dict) -> list[str]:
    calls = tool_calls(result)
    problems = _answered(result)
    if not any(c.get("name") == "shell" for c in calls):
        problems.append("never ran the tests with the shell tool")
    if any(c.get("name") == "terminal_session" for c in calls):
        problems.append("used terminal_session for a command that simply finishes")
    return problems


def check_reads_before_answering(result: dict, ctx: dict) -> list[str]:
    problems = _answered(result)
    reads = [
        c
        for c in tool_calls(result)
        if c.get("name") in {"filesystem", "grep", "shell"} and _touches(c, "math_utils")
    ]
    if not reads:
        problems.append("answered without opening math_utils.py")
    if (
        "sum" not in (result.get("result") or "").lower()
        and "add" not in (result.get("result") or "").lower()
    ):
        problems.append("the answer does not mention what add does")
    return problems


def check_fix_request_edits(result: dict, ctx: dict) -> list[str]:
    problems = _answered(result)
    edits = [
        c
        for c in tool_calls(result)
        if c.get("name") in {"edit", "filesystem", "shell"}
        and is_modifying(c)
        and _touches(c, "math_utils")
    ]
    if not edits:
        problems.append("was asked to fix the bug but never changed math_utils.py (over-cautious?)")
    workdir = ctx.get("workdir")
    if workdir is not None:
        source = (Path(workdir) / "math_utils.py").read_text(encoding="utf-8")
        if "return a - b" not in source:
            problems.append("math_utils.py still does not subtract")
    return problems


@dataclass
class Scenario:
    name: str
    prompt: str
    what: str
    check: Callable[[dict, dict], list[str]]


SCENARIOS = [
    Scenario(
        "question_no_changes",
        "What do you think could be improved in math_utils.py?",
        "an opinion question must be answered, not acted on (no edits, installs or state changes)",
        check_question_no_changes,
    ),
    Scenario(
        "run_tests_uses_shell",
        "Run the tests.",
        "a command that finishes uses `shell`, never a terminal session or a GUI window",
        check_run_tests_uses_shell,
    ),
    Scenario(
        "reads_before_answering",
        "What does the add function in math_utils.py do?",
        "it opens the file before answering instead of guessing",
        check_reads_before_answering,
    ),
    Scenario(
        "fix_request_edits",
        "Fix the bug in math_utils.py: subtract returns the sum instead of the difference.",
        "a request to change code still gets done (the prompt must not make it over-cautious)",
        check_fix_request_edits,
    ),
]


def build_fixture(directory: Path) -> None:
    for name, content in FIXTURE_FILES.items():
        (directory / name).write_text(content, encoding="utf-8")


def parse_result(stdout: str) -> dict | None:
    """The JSON object `--output json` prints (the last line that parses as one)."""
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def command_for(prompt: str, provider: str | None, model: str | None) -> list[str]:
    cmd = [
        sys.executable,
        "-c",
        "from cli.main import main; main()",
        "ask",
        "--output",
        "json",
        "--mode",
        "auto",
    ]
    if provider:
        cmd += ["-p", provider]
    if model:
        cmd += ["-m", model]
    return [*cmd, prompt]


def run_scenario(
    scenario: Scenario, provider: str | None, model: str | None, timeout: int, keep: bool = False
) -> tuple[bool, list[str]]:
    """Run one scenario in a fresh temp project. Returns (passed, reasons)."""
    workdir = Path(tempfile.mkdtemp(prefix="devorch-eval-"))
    try:
        build_fixture(workdir)
        try:
            proc = subprocess.run(
                command_for(scenario.prompt, provider, model),
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, [f"timed out after {timeout}s"]
        result = parse_result(proc.stdout)
        if result is None:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            return False, ["no JSON result", *tail]
        problems = scenario.check(result, {"workdir": workdir})
        return not problems, problems
    finally:
        if keep:
            print(f"    files kept in {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-p", "--provider")
    ap.add_argument("-m", "--model")
    ap.add_argument("--only", nargs="+", metavar="NAME", help="run only these scenarios")
    ap.add_argument("--list", action="store_true", help="list scenarios and exit")
    ap.add_argument("--timeout", type=int, default=300, help="seconds per scenario")
    ap.add_argument(
        "--keep", action="store_true", help="keep a copy of each scenario's final files"
    )
    args = ap.parse_args(argv)

    if args.list:
        for s in SCENARIOS:
            print(f"{s.name:24} {s.what}")
        return 0

    chosen = [s for s in SCENARIOS if not args.only or s.name in args.only]
    unknown = set(args.only or []) - {s.name for s in SCENARIOS}
    if unknown:
        print(f"unknown scenario(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    failures = 0
    for s in chosen:
        passed, reasons = run_scenario(s, args.provider, args.model, args.timeout, args.keep)
        print(f"{'PASS' if passed else 'FAIL'}  {s.name}")
        for r in reasons:
            print(f"        - {r}")
        failures += not passed
    print(f"\n{len(chosen) - failures}/{len(chosen)} scenarios passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
