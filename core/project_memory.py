"""
Persistent Per-Project Memory System for DevOrch.

Stores concise, token-efficient project context under ~/.devorch/projects/<project_id>/
so that DevOrch remembers architecture decisions, tech stack conventions, user preferences,
and recent task accomplishments across sessions without saving raw commands or bloat.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from schemas.message import Message

PROJECTS_DATA_DIR = Path.home() / ".devorch" / "projects"


def get_project_id(project_path: str | Path | None = None) -> str:
    """Generate a deterministic, human-readable project ID from a path.

    Example: 'c:/Users/ROGST/OneDrive/Documents/DevOrch' -> 'DevOrch_4e3b8641'
    """
    p = Path(project_path or os.getcwd()).resolve()
    # Normalize path string for consistent hashing across platforms
    normalized_path = str(p).replace("\\", "/").rstrip("/").lower()
    path_hash = hashlib.sha256(normalized_path.encode("utf-8")).hexdigest()[:8]

    # Clean name slug
    folder_name = p.name or "root"
    slug = re.sub(r"[^\w-]", "_", folder_name).strip("_")
    slug = slug[:24] if slug else "project"

    return f"{slug}_{path_hash}"


@dataclass
class ProjectMemory:
    """Structured memory for a single project workspace."""

    project_id: str
    project_name: str
    project_path: str
    tech_stack: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    recent_sessions: list[dict[str, str]] = field(default_factory=list)
    last_updated: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ProjectMemory:
        return cls(
            project_id=data.get("project_id", ""),
            project_name=data.get("project_name", ""),
            project_path=data.get("project_path", ""),
            tech_stack=data.get("tech_stack", []),
            decisions=data.get("decisions", []),
            preferences=data.get("preferences", []),
            recent_sessions=data.get("recent_sessions", []),
            last_updated=data.get("last_updated", datetime.now().strftime("%Y-%m-%d %H:%M")),
        )


class ProjectMemoryManager:
    """Manages persistent project memories across sessions."""

    def __init__(
        self,
        project_path: str | Path | None = None,
        base_dir: Path | None = None,
        max_recent_sessions: int = 4,
        max_prompt_chars: int = 1200,
    ):
        self.project_path = Path(project_path or os.getcwd()).resolve()
        self.project_id = get_project_id(self.project_path)
        self.base_dir = (base_dir or PROJECTS_DATA_DIR) / self.project_id
        self.memory_file = self.base_dir / "memory.json"
        self.markdown_file = self.base_dir / "MEMORY.md"
        self.max_recent_sessions = max_recent_sessions
        self.max_prompt_chars = max_prompt_chars
        self.memory = self.load()

    def _ensure_dir(self):
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> ProjectMemory:
        """Load project memory from disk, or initialize fresh instance."""
        if self.memory_file.exists():
            try:
                with open(self.memory_file, encoding="utf-8") as f:
                    data = json.load(f)
                mem = ProjectMemory.from_dict(data)
                # Keep path updated if project was moved
                mem.project_path = str(self.project_path)
                mem.project_name = self.project_path.name
                return mem
            except Exception:
                pass

        # Detect initial tech stack if new
        detected_stack = self._detect_tech_stack()

        return ProjectMemory(
            project_id=self.project_id,
            project_name=self.project_path.name or "project",
            project_path=str(self.project_path),
            tech_stack=detected_stack,
        )

    def save(self) -> None:
        """Persist memory to JSON and human-readable MEMORY.md."""
        self._ensure_dir()
        self.memory.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 1. Save JSON
        with open(self.memory_file, "w", encoding="utf-8") as f:
            json.dump(self.memory.to_dict(), f, indent=2)

        # 2. Save human-readable MEMORY.md
        md_lines = [
            f"# Project Memory: {self.memory.project_name}",
            f"\n- **Path**: `{self.memory.project_path}`",
            f"- **Last Updated**: {self.memory.last_updated}",
        ]

        if self.memory.tech_stack:
            md_lines.append(f"- **Tech Stack**: {', '.join(self.memory.tech_stack)}")

        if self.memory.decisions:
            md_lines.append("\n## Architectural Decisions & Conventions")
            for d in self.memory.decisions:
                md_lines.append(f"- {d}")

        if self.memory.preferences:
            md_lines.append("\n## User Preferences")
            for p in self.memory.preferences:
                md_lines.append(f"- {p}")

        if self.memory.recent_sessions:
            md_lines.append("\n## Recent Sessions")
            for s in self.memory.recent_sessions:
                s_id = s.get("session_id", "unknown")
                date = s.get("date", "")
                summary = s.get("summary", "").strip()
                md_lines.append(f"- **[{date}] Session `{s_id}`**: {summary}")

        with open(self.markdown_file, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines) + "\n")

    def add_decision(self, decision: str) -> None:
        """Add a key architectural decision (deduplicated)."""
        cleaned = decision.strip().rstrip(".")
        if cleaned and cleaned not in self.memory.decisions:
            self.memory.decisions.append(cleaned)
            # Keep decisions capped at 10 most relevant
            if len(self.memory.decisions) > 10:
                self.memory.decisions.pop(0)
            self.save()

    def add_preference(self, preference: str) -> None:
        """Add a learned user preference (deduplicated)."""
        cleaned = preference.strip().rstrip(".")
        if cleaned and cleaned not in self.memory.preferences:
            self.memory.preferences.append(cleaned)
            if len(self.memory.preferences) > 8:
                self.memory.preferences.pop(0)
            self.save()

    def clear(self) -> None:
        """Reset project memory for this workspace."""
        self.memory.decisions.clear()
        self.memory.preferences.clear()
        self.memory.recent_sessions.clear()
        self.save()

    def update_from_session(self, session_id: str | None, messages: list[Message]) -> str | None:
        """Extract high-level session accomplishments and update memory.

        Zero API token cost: uses heuristic analysis of user intents
        and assistant answers, strictly omitting shell commands, tool logs,
        and code dumps.
        """
        if not messages or not session_id:
            return None

        # Filter out sessions that were just aborted or empty
        user_msgs = [m.content.strip() for m in messages if m.role == "user"]
        assistant_msgs = [
            m.content.strip() for m in messages if m.role == "assistant" and m.content
        ]

        if not user_msgs or not assistant_msgs:
            return None

        # Extract primary goal from the first substantive user message
        first_goal = ""
        for u in user_msgs:
            if not u.startswith("/") and len(u) > 3:
                first_goal = u
                break

        if not first_goal:
            return None

        # Clean goal to 1 concise sentence (max 100 chars)
        goal_summary = first_goal.split("\n")[0].strip()
        if len(goal_summary) > 110:
            goal_summary = goal_summary[:107] + "..."

        # Extract accomplishment from last assistant message
        last_resp = assistant_msgs[-1]
        # Skip raw markdown codeblocks or giant dumps
        last_clean = re.sub(r"```[\s\S]*?```", "", last_resp).strip()
        lines = [
            line.strip()
            for line in last_clean.split("\n")
            if line.strip() and not line.strip().startswith("#")
        ]
        outcome = lines[0] if lines else "Completed requested tasks"
        if len(outcome) > 130:
            outcome = outcome[:127] + "..."

        session_summary = f"{goal_summary} -> {outcome}"

        # Avoid duplicate session entries
        existing_ids = [s.get("session_id") for s in self.memory.recent_sessions]
        if session_id in existing_ids:
            # Update existing entry
            for s in self.memory.recent_sessions:
                if s.get("session_id") == session_id:
                    s["summary"] = session_summary
                    s["date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    break
        else:
            self.memory.recent_sessions.append(
                {
                    "session_id": session_id,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "summary": session_summary,
                }
            )

        # Cap recent sessions to max_recent_sessions
        if len(self.memory.recent_sessions) > self.max_recent_sessions:
            self.memory.recent_sessions = self.memory.recent_sessions[-self.max_recent_sessions :]

        self.save()
        return session_summary

    def to_prompt_context(self) -> str:
        """Format a compact, token-budgeted memory block for the system prompt.

        Strictly bounded to ~200-300 tokens (max_prompt_chars), omitting
        raw commands, logs, and verbose content.
        """
        # Return empty if memory has no learned items
        has_content = (
            self.memory.decisions or self.memory.preferences or self.memory.recent_sessions
        )
        if not has_content:
            return ""

        lines = ["\n[PROJECT MEMORY (Persistent Cross-Session Context)]"]

        if self.memory.tech_stack:
            lines.append(f"- Tech Stack: {', '.join(self.memory.tech_stack[:6])}")

        if self.memory.decisions:
            lines.append("- Key Decisions & Conventions:")
            for d in self.memory.decisions[-6:]:
                lines.append(f"  * {d}")

        if self.memory.preferences:
            lines.append("- User Preferences:")
            for p in self.memory.preferences[-4:]:
                lines.append(f"  * {p}")

        if self.memory.recent_sessions:
            lines.append("- Recent Session Accomplishments:")
            for s in self.memory.recent_sessions[-3:]:
                lines.append(f"  * {s.get('summary', '')}")

        block = "\n".join(lines)

        # Enforce hard length cap so memory never blows token budget
        if len(block) > self.max_prompt_chars:
            block = block[: self.max_prompt_chars - 30] + "\n  * [older memories trimmed]"

        return block

    def _detect_tech_stack(self) -> list[str]:
        """Detect tech stack keywords from local project indicators."""
        stack = []
        p = self.project_path
        if (p / "pyproject.toml").exists() or (p / "setup.py").exists():
            stack.append("Python")
        if (p / "uv.lock").exists():
            stack.append("uv")
        if (p / "package.json").exists():
            stack.append("Node.js")
        if (p / "Cargo.toml").exists():
            stack.append("Rust")
        if (p / "go.mod").exists():
            stack.append("Go")
        if (p / "pytest.ini").exists() or (p / "tests").exists():
            stack.append("pytest")
        return stack
