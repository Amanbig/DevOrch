"""
Grep Tool - Search for patterns within file contents.
Similar to ripgrep/grep, optimized for code search.
"""

import os
import re
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from dataclasses import dataclass

from tools.base import Tool


@dataclass
class GrepMatch:
    """A single grep match result."""
    file: str
    line_number: int
    line_content: str
    match_start: int
    match_end: int


class GrepToolSchema(BaseModel):
    pattern: str = Field(..., description="Regex pattern to search for in file contents.")
    path: str = Field(default=".", description="File or directory to search in.")
    include: str = Field(default="*", description="File pattern to include (e.g., '*.py', '*.js').")
    context: int = Field(default=0, description="Number of context lines before and after match (0-5).")
    max_results: int = Field(default=50, description="Maximum number of results to return.")
    case_sensitive: bool = Field(default=True, description="Whether search is case-sensitive.")
    whole_word: bool = Field(default=False, description="Match whole words only.")


class GrepTool(Tool):
    """
    Searches for patterns within file contents.
    Returns matching lines with file paths and line numbers.
    """
    name = "grep"
    description = """Search for a pattern within file contents. Returns matching lines with file paths and line numbers.
Use this to find specific code, functions, variables, or text patterns across files.
Examples:
- Search for a function: pattern="def process_data"
- Search for imports: pattern="from typing import", include="*.py"
- Search for TODO comments: pattern="TODO|FIXME", include="*.py"
- Case-insensitive search: pattern="error", case_sensitive=false"""
    args_schema = GrepToolSchema

    # File extensions to search by default (text files)
    TEXT_EXTENSIONS = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.c', '.cpp', '.h', '.hpp',
        '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.scala', '.cs',
        '.html', '.css', '.scss', '.less', '.vue', '.svelte',
        '.json', '.yaml', '.yml', '.toml', '.xml', '.md', '.txt', '.rst',
        '.sh', '.bash', '.zsh', '.fish', '.ps1', '.bat', '.cmd',
        '.sql', '.graphql', '.proto',
        '.env', '.gitignore', '.dockerignore', 'Dockerfile', 'Makefile',
        '.cfg', '.ini', '.conf', '.config'
    }

    # Directories to skip
    SKIP_DIRS = {
        '.git', '.svn', '.hg', 'node_modules', '__pycache__', '.venv', 'venv',
        'env', '.env', 'dist', 'build', '.next', '.nuxt', 'target', 'out',
        '.idea', '.vscode', '.pytest_cache', '.mypy_cache', 'coverage',
        'htmlcov', '.tox', 'eggs', '*.egg-info'
    }

    def _should_search_file(self, filepath: str, include_pattern: str) -> bool:
        """Check if file should be searched based on extension and pattern."""
        filename = os.path.basename(filepath)
        ext = os.path.splitext(filename)[1].lower()

        # Check include pattern
        if include_pattern != "*":
            import fnmatch
            if not fnmatch.fnmatch(filename, include_pattern):
                return False

        # Check if it's a text file
        if ext and ext not in self.TEXT_EXTENSIONS:
            # Allow files without extension if they match pattern
            if ext:
                return False

        return True

    def _should_skip_dir(self, dirname: str) -> bool:
        """Check if directory should be skipped."""
        return dirname in self.SKIP_DIRS or dirname.startswith('.')

    def _search_file(
        self,
        filepath: str,
        regex: re.Pattern,
        context: int,
        max_results: int,
        current_results: int
    ) -> List[dict]:
        """Search a single file for matches."""
        results = []

        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            for i, line in enumerate(lines):
                if current_results + len(results) >= max_results:
                    break

                match = regex.search(line)
                if match:
                    result = {
                        "file": filepath,
                        "line": i + 1,
                        "content": line.rstrip('\n\r'),
                        "match": match.group()
                    }

                    # Add context lines if requested
                    if context > 0:
                        context_before = []
                        context_after = []

                        for j in range(max(0, i - context), i):
                            context_before.append(f"{j + 1}: {lines[j].rstrip()}")

                        for j in range(i + 1, min(len(lines), i + context + 1)):
                            context_after.append(f"{j + 1}: {lines[j].rstrip()}")

                        if context_before:
                            result["context_before"] = context_before
                        if context_after:
                            result["context_after"] = context_after

                    results.append(result)

        except Exception:
            pass  # Skip files that can't be read

        return results

    def run(self, arguments: Dict[str, Any]) -> Any:
        pattern = arguments.get("pattern")
        path = arguments.get("path", ".")
        include = arguments.get("include", "*")
        context = min(arguments.get("context", 0), 5)  # Max 5 context lines
        max_results = min(arguments.get("max_results", 50), 100)  # Max 100 results
        case_sensitive = arguments.get("case_sensitive", True)
        whole_word = arguments.get("whole_word", False)

        if not pattern:
            return "Error: Pattern not provided."

        # Build regex
        try:
            if whole_word:
                pattern = rf'\b{pattern}\b'

            flags = 0 if case_sensitive else re.IGNORECASE
            regex = re.compile(pattern, flags)
        except re.error as e:
            return f"Error: Invalid regex pattern - {e}"

        results = []

        # Handle single file
        if os.path.isfile(path):
            results = self._search_file(path, regex, context, max_results, 0)
        # Handle directory
        elif os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                # Skip certain directories
                dirs[:] = [d for d in dirs if not self._should_skip_dir(d)]

                for filename in files:
                    if len(results) >= max_results:
                        break

                    filepath = os.path.join(root, filename)

                    if self._should_search_file(filepath, include):
                        file_results = self._search_file(
                            filepath, regex, context, max_results, len(results)
                        )
                        results.extend(file_results)

                if len(results) >= max_results:
                    break
        else:
            return f"Error: Path '{path}' not found."

        if not results:
            return f"No matches found for pattern: {pattern}"

        # Format output
        output_lines = [f"Found {len(results)} match(es):\n"]

        for r in results:
            # Format: file:line: content
            output_lines.append(f"{r['file']}:{r['line']}: {r['content']}")

            if "context_before" in r:
                for ctx in r["context_before"]:
                    output_lines.append(f"  {ctx}")
                output_lines.append(f"  {r['line']}: {r['content']}  <-- match")
            if "context_after" in r:
                for ctx in r["context_after"]:
                    output_lines.append(f"  {ctx}")
                output_lines.append("")

        if len(results) >= max_results:
            output_lines.append(f"\n(Results truncated at {max_results})")

        return "\n".join(output_lines)
