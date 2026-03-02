"""
Edit Tool - Make targeted edits to files.
Supports find/replace, line-based edits, and smart code modifications.
"""

import os
import re
import difflib
from typing import Dict, Any, List, Optional, Literal
from pydantic import BaseModel, Field

from tools.base import Tool


class EditToolSchema(BaseModel):
    action: Literal["replace", "replace_lines", "insert", "delete", "patch"] = Field(
        ...,
        description="Edit action: replace (find/replace), replace_lines, insert, delete, patch"
    )
    path: str = Field(..., description="Path to the file to edit.")
    find: str = Field(default="", description="Text or pattern to find (for replace action).")
    replace_with: str = Field(default="", description="Replacement text.")
    line_start: int = Field(default=0, description="Start line number (1-indexed, for line-based actions).")
    line_end: int = Field(default=0, description="End line number (for replace_lines/delete).")
    content: str = Field(default="", description="Content for insert or patch action.")
    regex: bool = Field(default=False, description="Treat 'find' as regex pattern.")
    count: int = Field(default=1, description="Number of replacements (0 = all).")
    dry_run: bool = Field(default=False, description="Preview changes without applying.")


class EditTool(Tool):
    """
    Make targeted edits to files with precise control.
    Returns a diff showing the changes made.
    """
    name = "edit"
    description = """Make targeted edits to files. More precise than full file writes.

Actions:
- replace: Find and replace text (supports regex)
- replace_lines: Replace specific line range with new content
- insert: Insert content at a specific line
- delete: Delete lines in a range
- patch: Apply a unified diff patch

Examples:
- Replace text: action="replace", path="file.py", find="old_func", replace_with="new_func"
- Replace all: action="replace", path="file.py", find="TODO", replace_with="DONE", count=0
- Regex replace: action="replace", find="def (\\w+)\\(", replace_with="async def \\1(", regex=true
- Replace lines 10-15: action="replace_lines", line_start=10, line_end=15, content="new code"
- Insert at line 5: action="insert", line_start=5, content="# New comment"
- Delete lines 20-25: action="delete", line_start=20, line_end=25
- Preview changes: dry_run=true

Always use dry_run=true first to preview significant changes!"""
    args_schema = EditToolSchema

    def _read_file(self, path: str) -> List[str]:
        """Read file and return lines."""
        with open(path, 'r', encoding='utf-8') as f:
            return f.readlines()

    def _write_file(self, path: str, lines: List[str]):
        """Write lines to file."""
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

    def _generate_diff(
        self,
        original: List[str],
        modified: List[str],
        path: str
    ) -> str:
        """Generate a unified diff between original and modified content."""
        diff = difflib.unified_diff(
            original,
            modified,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm=''
        )
        return '\n'.join(diff)

    def _replace_text(
        self,
        lines: List[str],
        find: str,
        replace_with: str,
        regex: bool = False,
        count: int = 1
    ) -> tuple[List[str], int]:
        """Replace text in content. Returns (new_lines, replacement_count)."""
        content = ''.join(lines)
        replacements = 0

        if regex:
            try:
                pattern = re.compile(find)
                if count == 0:
                    new_content, replacements = pattern.subn(replace_with, content)
                else:
                    new_content, replacements = pattern.subn(replace_with, content, count=count)
            except re.error as e:
                raise ValueError(f"Invalid regex: {e}")
        else:
            if count == 0:
                replacements = content.count(find)
                new_content = content.replace(find, replace_with)
            else:
                new_content = content.replace(find, replace_with, count)
                replacements = min(content.count(find), count)

        # Preserve line structure
        if new_content and not new_content.endswith('\n') and lines and lines[-1].endswith('\n'):
            new_content += '\n'

        new_lines = new_content.splitlines(keepends=True)
        return new_lines, replacements

    def _replace_lines(
        self,
        lines: List[str],
        start: int,
        end: int,
        new_content: str
    ) -> List[str]:
        """Replace lines in range with new content."""
        # Convert to 0-indexed
        start_idx = max(0, start - 1)
        end_idx = min(len(lines), end)

        # Ensure new content ends with newline
        if new_content and not new_content.endswith('\n'):
            new_content += '\n'

        new_lines = new_content.splitlines(keepends=True) if new_content else []

        return lines[:start_idx] + new_lines + lines[end_idx:]

    def _insert_lines(
        self,
        lines: List[str],
        at_line: int,
        content: str
    ) -> List[str]:
        """Insert content at a specific line."""
        # Convert to 0-indexed
        insert_idx = max(0, min(len(lines), at_line - 1))

        # Ensure content ends with newline
        if content and not content.endswith('\n'):
            content += '\n'

        new_lines = content.splitlines(keepends=True) if content else []

        return lines[:insert_idx] + new_lines + lines[insert_idx:]

    def _delete_lines(
        self,
        lines: List[str],
        start: int,
        end: int
    ) -> List[str]:
        """Delete lines in range."""
        start_idx = max(0, start - 1)
        end_idx = min(len(lines), end)

        return lines[:start_idx] + lines[end_idx:]

    def run(self, arguments: Dict[str, Any]) -> Any:
        action = arguments.get("action")
        path = arguments.get("path")
        find = arguments.get("find", "")
        replace_with = arguments.get("replace_with", "")
        line_start = arguments.get("line_start", 0)
        line_end = arguments.get("line_end", 0)
        content = arguments.get("content", "")
        regex = arguments.get("regex", False)
        count = arguments.get("count", 1)
        dry_run = arguments.get("dry_run", False)

        if not path:
            return "Error: Path not provided."

        if not os.path.isfile(path):
            return f"Error: File '{path}' not found."

        try:
            original_lines = self._read_file(path)
            modified_lines = original_lines.copy()
            change_summary = ""

            if action == "replace":
                if not find:
                    return "Error: 'find' parameter required for replace action."

                modified_lines, num_replacements = self._replace_text(
                    modified_lines, find, replace_with, regex, count
                )

                if num_replacements == 0:
                    return f"No matches found for: {find}"

                change_summary = f"Replaced {num_replacements} occurrence(s)"

            elif action == "replace_lines":
                if line_start <= 0:
                    return "Error: line_start must be >= 1"
                if line_end <= 0:
                    line_end = line_start  # Replace single line

                if line_start > len(original_lines):
                    return f"Error: line_start ({line_start}) exceeds file length ({len(original_lines)})"

                modified_lines = self._replace_lines(
                    modified_lines, line_start, line_end, content
                )
                change_summary = f"Replaced lines {line_start}-{line_end}"

            elif action == "insert":
                if line_start <= 0:
                    return "Error: line_start must be >= 1"
                if not content:
                    return "Error: 'content' parameter required for insert action."

                modified_lines = self._insert_lines(modified_lines, line_start, content)
                inserted_count = len(content.splitlines())
                change_summary = f"Inserted {inserted_count} line(s) at line {line_start}"

            elif action == "delete":
                if line_start <= 0:
                    return "Error: line_start must be >= 1"
                if line_end <= 0:
                    line_end = line_start  # Delete single line

                if line_start > len(original_lines):
                    return f"Error: line_start ({line_start}) exceeds file length ({len(original_lines)})"

                modified_lines = self._delete_lines(modified_lines, line_start, line_end)
                deleted_count = min(line_end, len(original_lines)) - line_start + 1
                change_summary = f"Deleted {deleted_count} line(s) ({line_start}-{line_end})"

            elif action == "patch":
                # Apply a unified diff patch (more complex, basic implementation)
                return "Error: Patch action not yet implemented. Use replace_lines instead."

            else:
                return f"Error: Unknown action '{action}'"

            # Generate diff
            diff = self._generate_diff(original_lines, modified_lines, path)

            if not diff:
                return "No changes needed."

            if dry_run:
                return f"[DRY RUN] {change_summary}\n\nPreview:\n{diff}"

            # Apply changes
            self._write_file(path, modified_lines)

            return f"{change_summary}\n\nDiff:\n{diff}"

        except Exception as e:
            return f"Edit error: {str(e)}"
