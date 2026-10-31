"""How tool calls and their results look in the terminal.

Everything is built as ``rich.text.Text`` with explicit styles instead of markup strings. Paths,
commands, patterns and tool output are arbitrary text (``app/[id]/page.tsx``, ``List[int]``,
``echo "[/bold]"``); interpolating them into markup silently eats ``[...]`` or raises MarkupError and
kills the turn. The full result always goes to the model; this only controls what the user sees.
"""

from rich.text import Text

MAX_SHELL_LINES = 8
MAX_DIFF_LINES = 30
MAX_LINE_CHARS = 160
MAX_CMD_CHARS = 200
SHOW_DURATION_AFTER = 1.0  # seconds; faster calls don't need a timing

_BG = "on #1a1a28"


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _line(*parts: tuple[str, str]) -> Text:
    t = Text("  ")
    for content, style in parts:
        t.append(content, style=style)
    return t


def _call(label: str, detail: str = "", extra: str = "") -> Text:
    parts = [("> ", "dim"), (label, "cyan")]
    if detail:
        parts += [(" ", ""), (detail, "bold")]
    if extra:
        parts += [(" ", ""), (extra, "")]
    return _line(*parts)


def call_line(name: str, args: dict) -> Text | None:
    """One-line description of a tool call, or None when nothing should be shown."""
    if name == "task":
        return None  # the task panel shows progress

    if name == "shell":
        cmd = str(args.get("command", ""))
        first, *rest = cmd.splitlines() or [""]
        shown = _clip(first, MAX_CMD_CHARS)
        t = _line(("> ", "dim"), ("shell ", f"cyan {_BG}"), (shown, f"bold {_BG}"))
        if rest:
            t.append(f"  (+{len(rest)} more line{'s' if len(rest) != 1 else ''})", style="dim")
        return t

    if name == "filesystem":
        action = str(args.get("action", ""))
        path = str(args.get("path", ""))
        if action == "write":
            content = args.get("content", "") or ""
            lines = content.count("\n") + 1 if content else 0
            return _line(
                ("> ", "dim"), ("write ", "cyan"), (f"{lines} lines to ", ""), (path, "bold")
            )
        return _call(action or "filesystem", path)

    if name in ("search", "grep"):
        return _call(name, str(args.get("pattern", "")), f"in {args.get('path', '.')}")

    if name == "edit":
        return _call("edit", str(args.get("path", "")))

    if name == "websearch":
        return _call("searching web", str(args.get("query", "")))

    if name == "webfetch":
        return _call("fetching", _clip(str(args.get("url", "")), 60))

    if name == "memory":
        action = str(args.get("action", ""))
        if action == "save":
            return _call("saving memory", str(args.get("name", "")))
        if action == "search":
            return _call("searching memory", str(args.get("query", "")))
        if action == "list":
            return _call("listing memories")
        if action == "delete":
            return _call("deleting memory", str(args.get("filename", "")))
        return _call(f"memory {action}")

    if name == "git":
        action = str(args.get("action", ""))
        detail = str(args.get("ref") or " ".join(args.get("paths") or []) or "")
        return _call(f"git {action}".strip(), _clip(detail, 60))

    if name == "agent":
        task_lines = str(args.get("task", "")).splitlines()
        return _call("sub-agent", _clip(task_lines[0] if task_lines else "", 80))

    if name.startswith("mcp_"):
        return _line(("> ", "dim"), ("MCP ", "#6a8aaa"), (name, "cyan"))

    brief = {k: (_clip(v, 50) if isinstance(v, str) else v) for k, v in (args or {}).items()}
    return _call(name, extra=str(brief))


def _ok(text: str, elapsed: float | None = None) -> Text:
    t = Text("    ")
    t.append("✓ ", style="green")
    t.append(_clip(text, 100), style="dim")
    return _with_duration(t, elapsed)


def _with_duration(t: Text, elapsed: float | None) -> Text:
    if elapsed is not None and elapsed >= SHOW_DURATION_AFTER:
        t.append(f"  {elapsed:.1f}s", style="dim")
    return t


def _is_error(result: str) -> bool:
    """Tools report failure by *starting* the result with 'Error'. A file that merely contains
    the text 'Error:' (a read of source code, a log) is not an error."""
    return result.lstrip().startswith("Error")


def result_lines(name: str, result: object, elapsed: float | None = None) -> list[Text]:
    """What to show for a finished tool call."""
    text = str(result)

    if name == "task":
        return []

    if _is_error(text):
        t = Text("    ")
        t.append("✗ ", style="red")
        t.append(_clip(" ".join(text.split()), 300), style="red")
        return [_with_duration(t, elapsed)]

    if name == "filesystem":
        if "Successfully wrote" in text or "Successfully created" in text:
            return [_ok(text, elapsed)]
        if "] Lines " in text[:120]:
            return [_ok(text.split("\n", 1)[0], elapsed)]
        return [_ok(f"Done ({text.count(chr(10))} lines)", elapsed)]

    if name in ("search", "grep"):
        matches = [m for m in text.strip().split("\n") if m.strip()]
        return [_ok(f"Found {len(matches)} matches", elapsed)]

    if name == "websearch":
        n = sum(
            1
            for line in text.strip().split("\n")
            if line.strip().startswith(("1.", "2.", "3.", "4.", "5."))
        )
        return [_ok(f"Found {n} web results", elapsed)]

    if name == "webfetch":
        return [_ok(f"Fetched page ({text.count(chr(10))} lines)", elapsed)]

    if name == "memory":
        return [_ok(text.split("\n", 1)[0][:80], elapsed)]

    if name == "edit":
        return _edit_lines(text, elapsed)

    if text.startswith(("STDOUT:", "STDERR:")):
        return _shell_lines(text, elapsed)

    return [_ok(text.split("\n", 1)[0] or "Done", elapsed)]


def _footer(hidden: int, noun: str, elapsed: float | None) -> list[Text]:
    """'… +N more <noun>s' and/or the duration, as one trailing dim line (or nothing)."""
    show_time = elapsed is not None and elapsed >= SHOW_DURATION_AFTER
    if hidden <= 0 and not show_time:
        return []
    t = Text("    ")
    if hidden > 0:
        t.append(f"… +{hidden} more {noun}{'s' if hidden != 1 else ''}", style="dim")
    return [_with_duration(t, elapsed)]


def _shell_lines(text: str, elapsed: float | None) -> list[Text]:
    lines = text.rstrip("\n").split("\n")
    shown = lines[:MAX_SHELL_LINES]
    out = []
    for line in shown:
        t = Text("    ")
        t.append(_clip(line, MAX_LINE_CHARS), style=f"dim {_BG}")
        out.append(t)
    return out + _footer(len(lines) - len(shown), "line", elapsed)


def _edit_lines(text: str, elapsed: float | None) -> list[Text]:
    lines = text.split("\n")
    if not any(line.startswith(("---", "+++", "@@")) for line in lines):
        return [_ok(lines[0] if lines else "Done", elapsed)]
    out = []
    for line in lines[:MAX_DIFF_LINES]:
        if line.startswith(("+++ ", "--- ")):
            style = "dim"
        elif line.startswith("+"):
            style = "green"
        elif line.startswith("-"):
            style = "red"
        elif line.startswith("@@"):
            style = "cyan"
        else:
            style = "dim"
        out.append(Text("    " + _clip(line, MAX_LINE_CHARS), style=style))
    return out + _footer(len(lines) - MAX_DIFF_LINES, "diff line", elapsed)
