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
            # Handle different pattern formats
            if pattern.startswith("**/"):
                search_path = os.path.join(directory, pattern)
            elif "**" in pattern:
                search_path = os.path.join(directory, pattern)
            else:
                # Search recursively by default
                search_path = os.path.join(directory, "**", pattern)

            matches = glob.glob(search_path, recursive=True)

            # Filter results
            filtered = self._filter_results(matches, type_filter, include_hidden, max_results)

            if not filtered:
                return f"No files found matching: {pattern}"

            # Format output with file info
            output_lines = [f"Found {len(filtered)} result(s):\n"]

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

            if len(matches) > max_results:
                output_lines.append(f"\n(Showing {max_results} of {len(matches)} results)")

            return "\n".join(output_lines)

        except Exception as e:
            return f"Search error: {str(e)}"
