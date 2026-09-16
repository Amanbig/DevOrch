"""Project context loader and template generator for DevOrch.

Discovers and loads project-level instruction files (DEVORCH.md, CLAUDE.md, AGENTS.md)
to inform the AI agent about architecture, coding standards, build/test commands, and workflows.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from core.context import estimate_tokens

# Filenames to search for, in priority order
CANDIDATE_FILES = [
    "DEVORCH.md",
    ".devorch/rules.md",
    ".devorch/DEVORCH.md",
    ".devorch.md",
    "CLAUDE.md",
    ".claude/CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
]


@dataclass
class ProjectContext:
    """Loaded project rules or instructions."""

    file_path: Path
    file_name: str
    content: str
    truncated: bool = False
    estimated_tokens: int = 0

    def to_system_prompt_block(self) -> str:
        """Format the project rules for injection into the system prompt."""
        header = f"=== PROJECT GUIDELINES & CONTEXT (from {self.file_name}) ==="
        footer = f"=== END PROJECT GUIDELINES ({self.file_name}) ==="
        return f"\n{header}\n{self.content}\n{footer}\n"


class ProjectContextLoader:
    """Discovers and loads repository-level instructions."""

    def __init__(self, max_chars: int = 14000):
        self.max_chars = max_chars
        self._cached_context: ProjectContext | None = None
        self._cached_path: Path | None = None

    def find_context_file(self, start_dir: Path | str | None = None) -> Path | None:
        """Find the most relevant context file starting from start_dir up to repo root."""
        current = Path(start_dir or os.getcwd()).resolve()

        # Check current directory first
        for candidate in CANDIDATE_FILES:
            target = current / candidate
            if target.is_file():
                return target

        # Traverse upwards until root or git root
        for parent in current.parents:
            for candidate in CANDIDATE_FILES:
                target = parent / candidate
                if target.is_file():
                    return target
            if (parent / ".git").exists():
                break

        return None

    def load(self, start_dir: Path | str | None = None, force_reload: bool = False) -> ProjectContext | None:
        """Load project context from the nearest matching instruction file."""
        found = self.find_context_file(start_dir)
        if not found:
            return None

        if not force_reload and self._cached_path == found and self._cached_context:
            return self._cached_context

        try:
            with open(found, encoding="utf-8", errors="replace") as f:
                raw_content = f.read().strip()

            if not raw_content:
                return None

            truncated = False
            if len(raw_content) > self.max_chars:
                raw_content = (
                    raw_content[: self.max_chars]
                    + f"\n\n[... Remaining {len(raw_content) - self.max_chars} characters omitted for context limit ...]"
                )
                truncated = True

            context = ProjectContext(
                file_path=found,
                file_name=found.name,
                content=raw_content,
                truncated=truncated,
                estimated_tokens=estimate_tokens(raw_content),
            )
            self._cached_path = found
            self._cached_context = context
            return context

        except Exception:
            return None

    @staticmethod
    def generate_template(project_dir: Path | str | None = None) -> str:
        """Detect project stack and generate a customized DEVORCH.md template."""
        pdir = Path(project_dir or os.getcwd()).resolve()
        project_name = pdir.name

        # Detect tech stack
        has_python = (pdir / "pyproject.toml").exists() or (pdir / "setup.py").exists() or list(pdir.glob("*.py"))
        has_node = (pdir / "package.json").exists()
        has_rust = (pdir / "Cargo.toml").exists()
        has_go = (pdir / "go.mod").exists()

        commands_section = []
        conventions_section = []

        if has_python:
            commands_section.append("- **Run Tests**: `pytest` or `python -m pytest`")
            commands_section.append("- **Lint & Format**: `ruff check .` / `ruff format .`")
            conventions_section.append("- Use Python 3.10+ type annotations.")
            conventions_section.append("- Adhere to PEP 8 standards.")
        elif has_node:
            commands_section.append("- **Install**: `npm install` (or `pnpm install` / `yarn`)")
            commands_section.append("- **Run Dev**: `npm run dev`")
            commands_section.append("- **Run Tests**: `npm test`")
            commands_section.append("- **Build**: `npm run build`")
            conventions_section.append("- Use modern TypeScript / ES modules.")
        elif has_rust:
            commands_section.append("- **Build**: `cargo build`")
            commands_section.append("- **Test**: `cargo test`")
            commands_section.append("- **Check**: `cargo clippy`")
        elif has_go:
            commands_section.append("- **Build**: `go build ./...`")
            commands_section.append("- **Test**: `go test ./...`")
        else:
            commands_section.append("- **Build**: `[add build command]`")
            commands_section.append("- **Test**: `[add test command]`")

        commands_text = "\n".join(commands_section)
        conventions_text = "\n".join(conventions_section) or "- Write clean, modular, tested code."

        template = f"""# {project_name} - DevOrch Project Guidelines

## Overview
Brief description of the project and its core goals.

## Tech Stack
- Describe major languages, frameworks, and key libraries here.

## Common Commands
{commands_text}

## Code & Architecture Conventions
{conventions_text}
- Maintain minimal token usage: inspect files with `search` and `grep` before reading.
- Make targeted edits with `edit` tool rather than rewriting full files.
- Verify changes by running the relevant test commands.

## Important Notes & Gotchas
- Note any specific environment requirements, secrets setup, or architectural constraints.
"""
        return template

    @classmethod
    def init_project_file(cls, directory: Path | str | None = None, overwrite: bool = False) -> Path:
        """Create a new DEVORCH.md in the target directory."""
        pdir = Path(directory or os.getcwd()).resolve()
        target = pdir / "DEVORCH.md"

        if target.exists() and not overwrite:
            raise FileExistsError(f"File already exists: {target}")

        content = cls.generate_template(pdir)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)

        return target
