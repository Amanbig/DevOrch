"""
@file mentions — attach file or directory contents to a prompt.

    explain @core/agent.py
    what does @core/agent.py:100-140 do?
    summarize @tools/

A mention is only expanded when the path exists, so things like emails or ``@handles`` are left
alone. The original text is kept; the attached contents are appended in ``<file>`` blocks.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_CHARS_PER_FILE = 20_000
MAX_TOTAL_CHARS = 60_000
MAX_DIR_ENTRIES = 100

# '@' at a word boundary, a path, optional :start or :start-end line range
MENTION_RE = re.compile(r"(?<![\w@])@([\w./\\~+-]+)(?::(\d+)(?:-(\d+))?)?")


@dataclass
class MentionResult:
    prompt: str
    attached: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:4096]


def _read_file(path: Path, start: int | None, end: int | None) -> tuple[str | None, str | None]:
    """Return (text, warning)."""
    try:
        data = path.read_bytes()
    except OSError as e:
        return None, f"could not read {path}: {e}"
    if _is_binary(data):
        return None, f"skipped binary file {path}"
    lines = data.decode("utf-8", errors="replace").splitlines()
    first = 1
    if start:
        end = end or start
        first = max(1, start)
        lines = lines[first - 1 : max(first, end)]
    text = "\n".join(f"{first + i:>5}  {line}" for i, line in enumerate(lines))
    if len(text) > MAX_CHARS_PER_FILE:
        text = text[:MAX_CHARS_PER_FILE] + "\n... [truncated]"
    return text, None


def _list_dir(path: Path) -> str:
    entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    names = [e.name + ("/" if e.is_dir() else "") for e in entries if not e.name.startswith(".")]
    extra = len(names) - MAX_DIR_ENTRIES
    names = names[:MAX_DIR_ENTRIES]
    if extra > 0:
        names.append(f"... and {extra} more")
    return "\n".join(names)


def expand_mentions(text: str, cwd: Path | None = None) -> MentionResult:
    cwd = cwd or Path.cwd()
    result = MentionResult(prompt=text)
    blocks: list[str] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    total = 0

    for m in MENTION_RE.finditer(text):
        raw, start, end = m.group(1).rstrip(".,;)"), m.group(2), m.group(3)
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = cwd / path
        if not path.exists():
            continue
        key = (str(path), start, end)
        if key in seen:
            continue
        seen.add(key)

        label = raw + (f":{start}" + (f"-{end}" if end else "") if start else "")
        if path.is_dir():
            body, warn = _list_dir(path), None
            tag = f'<directory path="{raw}">'
            close = "</directory>"
        else:
            body, warn = _read_file(path, int(start) if start else None, int(end) if end else None)
            tag = f'<file path="{label}">'
            close = "</file>"
        if warn:
            result.warnings.append(warn)
            continue
        if total + len(body) > MAX_TOTAL_CHARS:
            result.warnings.append(f"skipped {label}: attachment size limit reached")
            continue
        total += len(body)
        blocks.append(f"{tag}\n{body}\n{close}")
        result.attached.append(label)

    if blocks:
        result.prompt = text + "\n\nAttached context:\n\n" + "\n\n".join(blocks)
    return result
