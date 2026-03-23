"""
Persistent memory system for DevOrch — stores user preferences, feedback,
project context, and references across conversations.

Memory files are stored as markdown with YAML frontmatter under
~/.devorch/memory/, with a MEMORY.md index file.
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tools.base import Tool

MEMORY_DIR = Path.home() / ".devorch" / "memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"

# Valid memory types
MEMORY_TYPES = {"user", "feedback", "project", "reference"}


def _ensure_memory_dir():
    """Create memory directory if needed."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content.
    Returns (metadata_dict, body_text).
    """
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    frontmatter = parts[1].strip()
    body = parts[2].strip()

    metadata = {}
    for line in frontmatter.split("\n"):
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            metadata[key.strip()] = value.strip()

    return metadata, body


def _create_frontmatter(name: str, description: str, mem_type: str) -> str:
    """Create YAML frontmatter block."""
    return f"""---
name: {name}
description: {description}
type: {mem_type}
created: {datetime.now().strftime('%Y-%m-%d %H:%M')}
---"""


def _slugify(text: str) -> str:
    """Convert text to a filename-safe slug."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "_", slug)
    return slug[:60].strip("_")


class MemoryManager:
    """Manages persistent memory files."""

    def __init__(self, memory_dir: Path | None = None):
        self.memory_dir = memory_dir or MEMORY_DIR
        self.index_file = self.memory_dir / "MEMORY.md"
        _ensure_memory_dir()

    def save(self, name: str, description: str, mem_type: str, content: str) -> str:
        """Save a memory to a markdown file and update the index.
        Returns the file path.
        """
        if mem_type not in MEMORY_TYPES:
            raise ValueError(f"Invalid memory type: {mem_type}. Must be one of: {MEMORY_TYPES}")

        filename = f"{mem_type}_{_slugify(name)}.md"
        filepath = self.memory_dir / filename

        frontmatter = _create_frontmatter(name, description, mem_type)
        file_content = f"{frontmatter}\n\n{content}\n"

        filepath.write_text(file_content, encoding="utf-8")

        # Update index
        self._update_index(filename, description, mem_type)

        return str(filepath)

    def load(self, filename: str) -> dict | None:
        """Load a specific memory file. Returns dict with metadata + body."""
        filepath = self.memory_dir / filename
        if not filepath.exists():
            return None

        content = filepath.read_text(encoding="utf-8")
        metadata, body = _parse_frontmatter(content)
        return {
            "filename": filename,
            "name": metadata.get("name", ""),
            "description": metadata.get("description", ""),
            "type": metadata.get("type", ""),
            "created": metadata.get("created", ""),
            "content": body,
        }

    def search(self, query: str = "", mem_type: str = "") -> list[dict]:
        """Search memories by keyword or type. Returns list of memory dicts."""
        results = []
        if not self.memory_dir.exists():
            return results

        for filepath in sorted(self.memory_dir.glob("*.md")):
            if filepath.name == "MEMORY.md":
                continue

            content = filepath.read_text(encoding="utf-8")
            metadata, body = _parse_frontmatter(content)

            # Filter by type
            if mem_type and metadata.get("type", "") != mem_type:
                continue

            # Filter by query (search name, description, and body)
            if query:
                searchable = f"{metadata.get('name', '')} {metadata.get('description', '')} {body}"
                if query.lower() not in searchable.lower():
                    continue

            results.append({
                "filename": filepath.name,
                "name": metadata.get("name", ""),
                "description": metadata.get("description", ""),
                "type": metadata.get("type", ""),
                "created": metadata.get("created", ""),
                "content": body,
            })

        return results

    def delete(self, filename: str) -> bool:
        """Delete a memory file and remove from index."""
        filepath = self.memory_dir / filename
        if not filepath.exists():
            return False

        filepath.unlink()
        self._remove_from_index(filename)
        return True

    def list_all(self) -> list[dict]:
        """List all memories with metadata (no body content)."""
        results = []
        if not self.memory_dir.exists():
            return results

        for filepath in sorted(self.memory_dir.glob("*.md")):
            if filepath.name == "MEMORY.md":
                continue

            content = filepath.read_text(encoding="utf-8")
            metadata, _ = _parse_frontmatter(content)

            results.append({
                "filename": filepath.name,
                "name": metadata.get("name", ""),
                "description": metadata.get("description", ""),
                "type": metadata.get("type", ""),
                "created": metadata.get("created", ""),
            })

        return results

    def get_context_prompt(self) -> str:
        """Build a context string from all memories for the system prompt."""
        memories = self.search()
        if not memories:
            return ""

        sections = {"user": [], "feedback": [], "project": [], "reference": []}

        for mem in memories:
            mem_type = mem.get("type", "")
            if mem_type in sections:
                sections[mem_type].append(mem)

        lines = ["\n## Memory Context (from previous conversations)\n"]

        type_labels = {
            "user": "User Profile",
            "feedback": "User Feedback & Preferences",
            "project": "Project Context",
            "reference": "External References",
        }

        for mem_type, label in type_labels.items():
            if sections[mem_type]:
                lines.append(f"\n### {label}")
                for mem in sections[mem_type]:
                    lines.append(f"- **{mem['name']}**: {mem['content'][:200]}")

        return "\n".join(lines)

    def _update_index(self, filename: str, description: str, mem_type: str):
        """Update the MEMORY.md index file."""
        _ensure_memory_dir()

        # Read existing index
        existing = ""
        if self.index_file.exists():
            existing = self.index_file.read_text(encoding="utf-8")

        # Check if entry already exists
        if filename in existing:
            # Update the line
            lines = existing.split("\n")
            new_lines = []
            for line in lines:
                if filename in line:
                    new_lines.append(f"- [{filename}]({filename}) — [{mem_type}] {description}")
                else:
                    new_lines.append(line)
            self.index_file.write_text("\n".join(new_lines), encoding="utf-8")
        else:
            # Append new entry
            if not existing:
                existing = "# DevOrch Memory Index\n\n"
            entry = f"- [{filename}]({filename}) — [{mem_type}] {description}\n"
            self.index_file.write_text(existing + entry, encoding="utf-8")

    def _remove_from_index(self, filename: str):
        """Remove an entry from the MEMORY.md index."""
        if not self.index_file.exists():
            return

        existing = self.index_file.read_text(encoding="utf-8")
        lines = existing.split("\n")
        new_lines = [line for line in lines if filename not in line]
        self.index_file.write_text("\n".join(new_lines), encoding="utf-8")


# ── Memory Tool for LLM use ─────────────────────────────────────────────────


class MemorySchema(BaseModel):
    action: str = Field(
        ...,
        description=(
            "Action to perform. One of: "
            "'save' — save a new memory; "
            "'search' — search existing memories; "
            "'list' — list all saved memories; "
            "'load' — load a specific memory by filename; "
            "'delete' — delete a memory by filename."
        ),
    )
    name: str | None = Field(
        None,
        description="Name/title for the memory. Required for 'save'.",
    )
    description: str | None = Field(
        None,
        description="One-line description of the memory. Required for 'save'.",
    )
    memory_type: str | None = Field(
        None,
        description=(
            "Type of memory. Required for 'save'. One of: "
            "'user' — user profile/preferences; "
            "'feedback' — user corrections/guidance; "
            "'project' — project context/decisions; "
            "'reference' — pointers to external resources."
        ),
    )
    content: str | None = Field(
        None,
        description="Memory content to save. Required for 'save'.",
    )
    query: str | None = Field(
        None,
        description="Search query for 'search' action. Searches name, description, and content.",
    )
    filename: str | None = Field(
        None,
        description="Filename for 'load' or 'delete' actions.",
    )


class MemoryTool(Tool):
    name = "memory"
    description = """\
Persistent memory system for storing and retrieving information across conversations.

Actions:
- **save** — Save information to persistent memory (requires name, description, memory_type, content)
- **search** — Search existing memories by keyword or type
- **list** — List all saved memories with their metadata
- **load** — Load a specific memory by filename
- **delete** — Delete a memory by filename

Memory Types:
- **user** — User profile, preferences, role, expertise
- **feedback** — User corrections, guidance on how to behave
- **project** — Project decisions, context, ongoing work
- **reference** — Links to external resources, documentation

Use this to remember important context about the user and project across conversations.
For feedback memories, structure as: rule, then Why: and How to apply: lines."""
    args_schema = MemorySchema

    def __init__(self):
        self._manager = MemoryManager()

    def run(self, arguments: dict[str, Any]) -> Any:
        action = (arguments.get("action") or "").lower().strip()

        if action == "save":
            name = arguments.get("name")
            description = arguments.get("description")
            mem_type = arguments.get("memory_type")
            content = arguments.get("content")

            if not all([name, description, mem_type, content]):
                return "Error: 'save' requires name, description, memory_type, and content."

            if mem_type not in MEMORY_TYPES:
                return f"Error: Invalid memory_type '{mem_type}'. Must be one of: {', '.join(MEMORY_TYPES)}"

            try:
                filepath = self._manager.save(name, description, mem_type, content)
                return f"Memory saved: {name}\nFile: {filepath}"
            except Exception as e:
                return f"Error saving memory: {e}"

        elif action == "search":
            query = arguments.get("query", "")
            mem_type = arguments.get("memory_type", "")
            results = self._manager.search(query=query, mem_type=mem_type)

            if not results:
                return "No memories found matching your search."

            lines = [f"Found {len(results)} memory(ies):\n"]
            for mem in results:
                preview = mem["content"][:100].replace("\n", " ")
                lines.append(
                    f"  [{mem['type']}] {mem['name']}\n"
                    f"    File: {mem['filename']}\n"
                    f"    {preview}...\n"
                )
            return "\n".join(lines)

        elif action == "list":
            memories = self._manager.list_all()
            if not memories:
                return "No memories saved yet."

            lines = ["Saved memories:\n"]
            for mem in memories:
                lines.append(
                    f"  [{mem['type']}] {mem['name']}\n"
                    f"    {mem['description']}\n"
                    f"    File: {mem['filename']}  Created: {mem['created']}\n"
                )
            return "\n".join(lines)

        elif action == "load":
            filename = arguments.get("filename")
            if not filename:
                return "Error: 'load' requires filename."

            mem = self._manager.load(filename)
            if not mem:
                return f"Error: Memory '{filename}' not found."

            return (
                f"Name: {mem['name']}\n"
                f"Type: {mem['type']}\n"
                f"Description: {mem['description']}\n"
                f"Created: {mem['created']}\n\n"
                f"{mem['content']}"
            )

        elif action == "delete":
            filename = arguments.get("filename")
            if not filename:
                return "Error: 'delete' requires filename."

            if self._manager.delete(filename):
                return f"Memory '{filename}' deleted."
            else:
                return f"Error: Memory '{filename}' not found."

        else:
            return (
                f"Error: Unknown action '{action}'. "
                f"Valid actions: save, search, list, load, delete."
            )
