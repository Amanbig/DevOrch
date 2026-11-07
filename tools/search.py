import glob
import os
from typing import Any

from pydantic import BaseModel, Field

from tools.base import Tool


class SearchToolSchema(BaseModel):
    pattern: str = Field(..., description="Glob pattern (e.g., '*.py', 'test_*.js', '**/*.md').")
    directory: str = Field(default=".", description="Directory to search in.")
    type: str = Field(default="all", description="Filter: 'file', 'dir', or 'all'.")
    max_results: int = Field(default=100, description="Maximum number of results.")
    include_hidden: bool = Field(default=False, description="Include hidden files/directories.")


def strip_directory_prefix(pattern: str, directory: str) -> str | None:
    """Remove the searched directory's own name from the front of a pattern, or None if absent.

    Patterns are relative to ``directory``, but models often include it anyway, e.g. pattern
    ``**/cli/commands/*.py`` with directory ``cli``, which can never match. ``**/cli/commands/*.py``
    becomes ``**/commands/*.py``.
    """
    pat = pattern.replace("\\", "/").split("/")
    dir_parts = [
        p for p in os.path.normpath(directory).replace("\\", "/").split("/") if p and p != "."
    ]
    i = 0
    while i < len(pat) and pat[i] == "**":
        i += 1
    for k in range(min(len(dir_parts), len(pat) - i), 0, -1):
        if pat[i : i + k] == dir_parts[-k:]:
            rest = pat[:i] + pat[i + k :]
            return "/".join(rest) if rest else None
    return None


class SearchTool(Tool):
    name = "search"
    description = """Search for files and directories matching a glob pattern.

Examples:
- Find Python files: pattern="*.py"
- Find test files: pattern="test_*.py"
- Find all in subdirs: pattern="**/*.js"
- Find specific file: pattern="**/config.yaml"
- Find directories: pattern="**/tests", type="dir"
- Find markdown docs: pattern="**/*.md", directory="docs"

Common patterns:
- *.ext - Files with extension in current dir
- **/*.ext - Files with extension in all subdirs
- **/name - File/dir with exact name in all subdirs
- prefix* - Files starting with prefix
- *suffix - Files ending with suffix"""
    args_schema = SearchToolSchema

    # Directories to skip by default
    SKIP_DIRS = {
        ".git",
        ".svn",
        ".hg",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        ".env",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "target",
        "out",
        ".idea",
        ".vscode",
        ".pytest_cache",
        ".mypy_cache",
    }

    def _filter_results(
        self, matches: list[str], type_filter: str, include_hidden: bool, max_results: int
    ) -> list[str]:
        """Filter and limit results."""
        filtered = []

        for match in matches:
            # Skip hidden unless requested
            if not include_hidden:
                parts = match.replace("\\", "/").split("/")
                if any(p.startswith(".") and p not in (".", "..") for p in parts):
                    continue

                # Skip common ignored directories
                if any(skip in parts for skip in self.SKIP_DIRS):
                    continue

            # Type filter
            if type_filter == "file" and not os.path.isfile(match):
                continue
            if type_filter == "dir" and not os.path.isdir(match):
                continue

            filtered.append(match)

            if len(filtered) >= max_results:
                break

        return filtered

    def _find(
        self,
        pattern: str,
        directory: str,
        type_filter: str,
        include_hidden: bool,
        max_results: int,
    ) -> tuple[list[str], int]:
        """Glob ``pattern`` under ``directory``. Returns (filtered matches, total before the cap)."""
        if pattern.startswith("**/") or "**" in pattern:
            search_path = os.path.join(directory, pattern)
        else:
            search_path = os.path.join(directory, "**", pattern)  # recursive by default
        matches = glob.glob(search_path, recursive=True)
        return self._filter_results(matches, type_filter, include_hidden, max_results), len(matches)

    def _nothing_found(self, pattern: str, directory: str) -> str:
        """An empty result that explains itself, so a model does not decide the folder is empty."""
        lines = [f"No files found matching: {pattern}"]
        try:
            entries = sorted(
                (
                    e
                    for e in os.listdir(directory)
                    if not e.startswith(".") and e not in self.SKIP_DIRS
                ),
                key=lambda e: (not os.path.isdir(os.path.join(directory, e)), e.lower()),
            )
        except OSError:
            entries = []
        lines.append(
            f"Patterns are relative to '{directory}' and searched recursively (don't repeat the "
            f"directory name in the pattern)."
        )
        if entries:
            shown = [
                e + ("/" if os.path.isdir(os.path.join(directory, e)) else "") for e in entries[:10]
            ]
            more = f" ... and {len(entries) - 10} more" if len(entries) > 10 else ""
            lines.append(f"'{directory}' contains: {', '.join(shown)}{more}")
            lines.append("Try a broader pattern such as '**/*.py', or list the directory first.")
        else:
            lines.append(f"'{directory}' is empty (or only has hidden files).")
        return "\n".join(lines)

    def run(self, arguments: dict[str, Any]) -> Any:
        pattern = arguments.get("pattern")
        directory = arguments.get("directory", ".")
        type_filter = arguments.get("type", "all").lower()
        max_results = min(arguments.get("max_results", 100), 500)
        include_hidden = arguments.get("include_hidden", False)

        if not pattern:
            return "Error: Pattern not provided."

        if not os.path.isdir(directory):
            return f"Error: Directory '{directory}' not found."

        try:
            note = ""
            filtered, total = self._find(
                pattern, directory, type_filter, include_hidden, max_results
            )

            if not filtered:
                stripped = strip_directory_prefix(pattern, directory)
                if stripped:
                    filtered, total = self._find(
                        stripped, directory, type_filter, include_hidden, max_results
                    )
                    if filtered:
                        note = (
                            f"(Patterns are relative to '{directory}', so I searched for "
                            f"'{stripped}' instead of '{pattern}'.)\n\n"
                        )

            if not filtered:
                return self._nothing_found(pattern, directory)

            # Format output with file info
            output_lines = [f"{note}Found {len(filtered)} result(s):\n"]

            for match in filtered:
                # Normalize path
                rel_path = os.path.relpath(match, directory) if directory != "." else match

                if os.path.isdir(match):
                    output_lines.append(f"  [DIR]  {rel_path}/")
                else:
                    try:
                        size = os.path.getsize(match)
                        if size < 1024:
                            size_str = f"{size}B"
                        elif size < 1024 * 1024:
                            size_str = f"{size // 1024}KB"
                        else:
                            size_str = f"{size // (1024 * 1024)}MB"
                        output_lines.append(f"  {size_str:>6}  {rel_path}")
                    except Exception:
                        output_lines.append(f"  {'?':>6}  {rel_path}")

            if total > max_results:
                output_lines.append(f"\n(Showing {max_results} of {total} results)")

            return "\n".join(output_lines)

        except Exception as e:
            return f"Search error: {str(e)}"
