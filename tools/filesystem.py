import os
from typing import Any, Literal

from pydantic import BaseModel, Field

from tools.base import Tool


class FilesystemToolSchema(BaseModel):
    action: Literal["read", "write", "list", "read_lines", "info"] = Field(
        ..., description="Action: read (full file), read_lines (specific lines), write, list, info"
    )
    path: str = Field(..., description="Path to the file or directory.")
    content: str = Field(default="", description="Content to write (only for 'write' action).")
    start_line: int = Field(default=1, description="Start line number for read_lines (1-indexed).")
    end_line: int = Field(
        default=0, description="End line number for read_lines (0 = to end of file)."
    )
    max_lines: int = Field(default=200, description="Maximum lines to return for read action.")


class FilesystemTool(Tool):
    name = "filesystem"
    description = """Read, write, or list files and directories with line-specific control.

Actions:
- read: Read file content (with line numbers, truncated at max_lines)
- read_lines: Read specific line range (start_line to end_line)
- write: Write content to file
- list: List directory contents with file info
- info: Get file metadata (size, modified date, line count)

Examples:
- Read first 50 lines: action="read", path="file.py", max_lines=50
- Read lines 100-150: action="read_lines", path="file.py", start_line=100, end_line=150
- Get file info: action="info", path="file.py"
"""
    args_schema = FilesystemToolSchema

    def _format_size(self, size: int) -> str:
        """Format file size in human-readable format."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"

    def _count_lines(self, path: str) -> int:
        """Count lines in a file efficiently."""
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                return sum(1 for _ in f)
        except Exception:
            return -1

    def _read_with_line_numbers(
        self, path: str, start_line: int = 1, end_line: int = 0, max_lines: int = 200
    ) -> str:
        """Read file with line numbers, supporting line ranges."""
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            total_lines = len(lines)

            # Adjust line numbers (1-indexed)
            start_idx = max(0, start_line - 1)
            if end_line > 0:
                end_idx = min(total_lines, end_line)
            else:
                end_idx = min(start_idx + max_lines, total_lines)

            # Build output with line numbers
            output_lines = []
            line_num_width = len(str(end_idx))

            for i in range(start_idx, end_idx):
                line_num = str(i + 1).rjust(line_num_width)
                output_lines.append(f"{line_num} | {lines[i].rstrip()}")

            # Add truncation notice if needed
            header = f"[{path}] Lines {start_idx + 1}-{end_idx} of {total_lines}\n"

            if end_idx < total_lines and end_line == 0:
                footer = f"\n... ({total_lines - end_idx} more lines)"
            else:
                footer = ""

            return header + "\n".join(output_lines) + footer

        except Exception as e:
            return f"Error reading file: {str(e)}"

    def _list_directory(self, path: str) -> str:
        """List directory with file info."""
        try:
            items = os.listdir(path)
            if not items:
                return "Directory is empty."

            output = []
            dirs = []
            files = []

            for item in sorted(items):
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    dirs.append(f"  [DIR]  {item}/")
                else:
                    try:
                        size = os.path.getsize(item_path)
                        size_str = self._format_size(size)
                        files.append(f"  {size_str:>8}  {item}")
                    except Exception:
                        files.append(f"  {'?':>8}  {item}")

            if dirs:
                output.append("Directories:")
                output.extend(dirs)
            if files:
                if dirs:
                    output.append("")
                output.append("Files:")
                output.extend(files)

            return "\n".join(output)

        except Exception as e:
            return f"Error listing directory: {str(e)}"

    def _get_file_info(self, path: str) -> str:
        """Get file metadata."""
        try:
            stat = os.stat(path)
            size = self._format_size(stat.st_size)
            modified = os.path.getmtime(path)

            from datetime import datetime

            mod_date = datetime.fromtimestamp(modified).strftime("%Y-%m-%d %H:%M:%S")

            info = [
                f"Path: {os.path.abspath(path)}",
                f"Size: {size} ({stat.st_size} bytes)",
                f"Modified: {mod_date}",
            ]

            # Add line count for text files
            ext = os.path.splitext(path)[1].lower()
            text_exts = {
                ".py",
                ".js",
                ".ts",
                ".json",
                ".yaml",
                ".yml",
                ".md",
                ".txt",
                ".html",
                ".css",
            }
            if ext in text_exts or not ext:
                line_count = self._count_lines(path)
                if line_count >= 0:
                    info.append(f"Lines: {line_count}")

            return "\n".join(info)

        except Exception as e:
            return f"Error getting file info: {str(e)}"

    def run(self, arguments: dict[str, Any]) -> Any:
        action = arguments.get("action")
        path = arguments.get("path")
        content = arguments.get("content", "")
        start_line = arguments.get("start_line", 1)
        end_line = arguments.get("end_line", 0)
        max_lines = min(arguments.get("max_lines", 200), 500)  # Cap at 500

        if not path:
            return "Error: Path not provided."

        try:
            if action == "read":
                if not os.path.isfile(path):
                    return f"Error: File '{path}' not found."
                return self._read_with_line_numbers(path, max_lines=max_lines)

            elif action == "read_lines":
                if not os.path.isfile(path):
                    return f"Error: File '{path}' not found."
                return self._read_with_line_numbers(path, start_line, end_line, max_lines=500)

            elif action == "write":
                # Create directory if needed
                dir_path = os.path.dirname(path)
                if dir_path and not os.path.exists(dir_path):
                    os.makedirs(dir_path)

                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)

                line_count = content.count("\n") + (
                    1 if content and not content.endswith("\n") else 0
                )
                return f"Successfully wrote {line_count} lines to {path}"

            elif action == "list":
                if not os.path.exists(path):
                    return f"Error: Path '{path}' does not exist."
                if os.path.isfile(path):
                    return self._get_file_info(path)
                return self._list_directory(path)

            elif action == "info":
                if not os.path.exists(path):
                    return f"Error: Path '{path}' does not exist."
                return self._get_file_info(path)

            else:
                return f"Error: Unknown action '{action}'. Use: read, read_lines, write, list, info"

        except Exception as e:
            return f"Filesystem error: {str(e)}"
