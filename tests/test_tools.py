"""Tests for tool implementations."""

import os
import tempfile
from pathlib import Path

import pytest

from tools.edit import EditTool
from tools.filesystem import FilesystemTool
from tools.grep import GrepTool
from tools.search import SearchTool
from tools.task import TaskTool


class TestToolBase:
    """Tests for Tool base class."""

    def test_tool_schema_generation(self):
        """Test that tools generate correct schema."""
        tool = FilesystemTool()
        schema = tool.schema()

        assert schema["name"] == "filesystem"
        assert "description" in schema
        assert "parameters" in schema
        assert schema["parameters"]["type"] == "object"
        assert "properties" in schema["parameters"]


class TestFilesystemTool:
    """Tests for FilesystemTool."""

    @pytest.fixture
    def tool(self):
        return FilesystemTool()

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory with test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n")

            py_file = Path(tmpdir) / "test.py"
            py_file.write_text("def hello():\n    print('Hello')\n")

            subdir = Path(tmpdir) / "subdir"
            subdir.mkdir()
            sub_file = subdir / "nested.txt"
            sub_file.write_text("Nested content\n")

            yield tmpdir

    def test_read_file(self, tool, temp_dir):
        """Test reading a file."""
        path = os.path.join(temp_dir, "test.txt")
        result = tool.run({"action": "read", "path": path})

        assert "Line 1" in result
        assert "Line 5" in result
        assert "test.txt" in result

    def test_read_file_not_found(self, tool, temp_dir):
        """Test reading a non-existent file."""
        path = os.path.join(temp_dir, "nonexistent.txt")
        result = tool.run({"action": "read", "path": path})

        assert "Error" in result
        assert "not found" in result

    def test_read_lines(self, tool, temp_dir):
        """Test reading specific lines."""
        path = os.path.join(temp_dir, "test.txt")
        result = tool.run({"action": "read_lines", "path": path, "start_line": 2, "end_line": 4})

        assert "Line 2" in result
        assert "Line 3" in result
        assert "Line 4" in result

    def test_write_file(self, tool, temp_dir):
        """Test writing a file."""
        path = os.path.join(temp_dir, "new_file.txt")
        result = tool.run(
            {"action": "write", "path": path, "content": "New content\nSecond line\n"}
        )

        assert "Successfully wrote" in result
        assert os.path.exists(path)

        with open(path) as f:
            content = f.read()
        assert "New content" in content

    def test_write_creates_directories(self, tool, temp_dir):
        """Test that write creates parent directories."""
        path = os.path.join(temp_dir, "new_dir", "nested", "file.txt")
        result = tool.run({"action": "write", "path": path, "content": "Content"})

        assert "Successfully wrote" in result
        assert os.path.exists(path)

    def test_list_directory(self, tool, temp_dir):
        """Test listing a directory."""
        result = tool.run({"action": "list", "path": temp_dir})

        assert "test.txt" in result
        assert "test.py" in result
        assert "subdir" in result

    def test_list_empty_directory(self, tool, temp_dir):
        """Test listing an empty directory."""
        empty_dir = os.path.join(temp_dir, "empty")
        os.makedirs(empty_dir)

        result = tool.run({"action": "list", "path": empty_dir})
        assert "empty" in result.lower()

    def test_info_file(self, tool, temp_dir):
        """Test getting file info."""
        path = os.path.join(temp_dir, "test.py")
        result = tool.run({"action": "info", "path": path})

        assert "Path:" in result
        assert "Size:" in result
        assert "Modified:" in result
        assert "Lines:" in result

    def test_path_not_provided(self, tool):
        """Test error when path not provided."""
        result = tool.run({"action": "read", "path": ""})
        assert "Error" in result

    def test_unknown_action(self, tool, temp_dir):
        """Test error for unknown action."""
        path = os.path.join(temp_dir, "test.txt")
        result = tool.run({"action": "unknown", "path": path})
        assert "Error" in result
        assert "Unknown action" in result


class TestSearchTool:
    """Tests for SearchTool."""

    @pytest.fixture
    def tool(self):
        return SearchTool()

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory with test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / "file1.py").write_text("content")
            (Path(tmpdir) / "file2.py").write_text("content")
            (Path(tmpdir) / "test_file.py").write_text("content")
            (Path(tmpdir) / "readme.md").write_text("content")

            subdir = Path(tmpdir) / "src"
            subdir.mkdir()
            (subdir / "main.py").write_text("content")
            (subdir / "utils.py").write_text("content")

            yield tmpdir

    def test_search_py_files(self, tool, temp_dir):
        """Test searching for Python files."""
        result = tool.run({"pattern": "*.py", "directory": temp_dir})

        assert "Found" in result
        assert ".py" in result

    def test_search_test_files(self, tool, temp_dir):
        """Test searching for test files."""
        result = tool.run({"pattern": "test_*.py", "directory": temp_dir})

        assert "Found" in result
        assert "test_file.py" in result

    def test_search_recursive(self, tool, temp_dir):
        """Test recursive search."""
        result = tool.run({"pattern": "**/*.py", "directory": temp_dir})

        assert "Found" in result
        assert "main.py" in result or "src" in result

    def test_search_no_results(self, tool, temp_dir):
        """Test search with no matches."""
        result = tool.run({"pattern": "*.xyz", "directory": temp_dir})

        assert "No files found" in result

    def test_search_invalid_directory(self, tool):
        """Test search in non-existent directory."""
        result = tool.run({"pattern": "*.py", "directory": "/nonexistent"})

        assert "Error" in result
        assert "not found" in result

    def test_search_no_pattern(self, tool, temp_dir):
        """Test error when no pattern provided."""
        result = tool.run({"pattern": "", "directory": temp_dir})

        assert "Error" in result


class TestGrepTool:
    """Tests for GrepTool."""

    @pytest.fixture
    def tool(self):
        return GrepTool()

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory with test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files with searchable content
            file1 = Path(tmpdir) / "main.py"
            file1.write_text("""def hello():
    print("Hello, World!")

def goodbye():
    print("Goodbye!")

# TODO: Add more functions
""")

            file2 = Path(tmpdir) / "utils.py"
            file2.write_text("""def helper():
    return "helper"

def hello_helper():
    return hello()
""")

            yield tmpdir

    def test_grep_simple_pattern(self, tool, temp_dir):
        """Test simple text search."""
        result = tool.run({"pattern": "def hello", "path": temp_dir})

        assert "Found" in result
        assert "def hello" in result

    def test_grep_regex_pattern(self, tool, temp_dir):
        """Test regex pattern search."""
        result = tool.run({"pattern": r"def \w+\(\)", "path": temp_dir})

        assert "Found" in result
        assert "match" in result.lower()

    def test_grep_case_insensitive(self, tool, temp_dir):
        """Test case-insensitive search."""
        result = tool.run({"pattern": "HELLO", "path": temp_dir, "case_sensitive": False})

        assert "Found" in result

    def test_grep_with_include(self, tool, temp_dir):
        """Test search with file pattern filter."""
        result = tool.run({"pattern": "helper", "path": temp_dir, "include": "utils.py"})

        assert "Found" in result
        assert "utils.py" in result

    def test_grep_single_file(self, tool, temp_dir):
        """Test searching a single file."""
        path = os.path.join(temp_dir, "main.py")
        result = tool.run({"pattern": "TODO", "path": path})

        assert "Found" in result
        assert "TODO" in result

    def test_grep_no_matches(self, tool, temp_dir):
        """Test search with no matches."""
        result = tool.run({"pattern": "nonexistent_pattern_xyz", "path": temp_dir})

        assert "No matches found" in result

    def test_grep_invalid_regex(self, tool, temp_dir):
        """Test error with invalid regex."""
        result = tool.run({"pattern": "[invalid", "path": temp_dir})

        assert "Error" in result

    def test_grep_whole_word(self, tool, temp_dir):
        """Test whole word matching."""
        result = tool.run({"pattern": "hello", "path": temp_dir, "whole_word": True})

        # Should match "def hello" but not "hello_helper"
        assert "Found" in result

    def test_grep_with_context(self, tool, temp_dir):
        """Test search with context lines."""
        result = tool.run({"pattern": "TODO", "path": temp_dir, "context": 2})

        assert "Found" in result


class TestEditTool:
    """Tests for EditTool."""

    @pytest.fixture
    def tool(self):
        return EditTool()

    @pytest.fixture
    def temp_file(self):
        """Create a temporary test file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("""def old_function():
    pass

def another_function():
    old_value = 1
    return old_value
""")
            path = f.name

        yield path
        os.unlink(path)

    def test_replace_text(self, tool, temp_file):
        """Test find and replace."""
        result = tool.run(
            {
                "action": "replace",
                "path": temp_file,
                "find": "old_function",
                "replace_with": "new_function",
            }
        )

        assert "Replaced" in result
        with open(temp_file) as f:
            content = f.read()
        assert "new_function" in content

    def test_replace_all(self, tool, temp_file):
        """Test replacing all occurrences."""
        result = tool.run(
            {
                "action": "replace",
                "path": temp_file,
                "find": "old",
                "replace_with": "new",
                "count": 0,  # Replace all
            }
        )

        assert "Replaced" in result
        with open(temp_file) as f:
            content = f.read()
        assert "old" not in content
        assert "new_function" in content
        assert "new_value" in content

    def test_replace_regex(self, tool, temp_file):
        """Test regex replacement."""
        result = tool.run(
            {
                "action": "replace",
                "path": temp_file,
                "find": r"def (\w+)\(",
                "replace_with": r"async def \1(",
                "regex": True,
                "count": 1,
            }
        )

        assert "Replaced" in result
        with open(temp_file) as f:
            content = f.read()
        assert "async def" in content

    def test_replace_no_match(self, tool, temp_file):
        """Test replace with no matches."""
        result = tool.run(
            {
                "action": "replace",
                "path": temp_file,
                "find": "nonexistent_text",
                "replace_with": "new_text",
            }
        )

        assert "No matches found" in result

    def test_replace_lines(self, tool, temp_file):
        """Test replacing line range."""
        result = tool.run(
            {
                "action": "replace_lines",
                "path": temp_file,
                "line_start": 1,
                "line_end": 2,
                "content": "def replaced_function():\n    return True\n",
            }
        )

        assert "Replaced lines" in result
        with open(temp_file) as f:
            content = f.read()
        assert "replaced_function" in content

    def test_insert_lines(self, tool, temp_file):
        """Test inserting content."""
        result = tool.run(
            {
                "action": "insert",
                "path": temp_file,
                "line_start": 1,
                "content": "# New comment at top\n",
            }
        )

        assert "Inserted" in result
        with open(temp_file) as f:
            lines = f.readlines()
        assert "# New comment" in lines[0]

    def test_delete_lines(self, tool, temp_file):
        """Test deleting lines."""
        with open(temp_file) as f:
            original_lines = len(f.readlines())

        result = tool.run({"action": "delete", "path": temp_file, "line_start": 1, "line_end": 2})

        assert "Deleted" in result
        with open(temp_file) as f:
            new_lines = len(f.readlines())
        assert new_lines < original_lines

    def test_dry_run(self, tool, temp_file):
        """Test dry run mode."""
        with open(temp_file) as f:
            original = f.read()

        result = tool.run(
            {
                "action": "replace",
                "path": temp_file,
                "find": "old_function",
                "replace_with": "dry_run_function",
                "dry_run": True,
            }
        )

        assert "DRY RUN" in result
        with open(temp_file) as f:
            after = f.read()
        assert original == after  # File unchanged

    def test_file_not_found(self, tool):
        """Test error for non-existent file."""
        result = tool.run(
            {
                "action": "replace",
                "path": "/nonexistent/file.txt",
                "find": "text",
                "replace_with": "new",
            }
        )

        assert "Error" in result
        assert "not found" in result

    def test_invalid_action(self, tool, temp_file):
        """Test error for unknown action."""
        result = tool.run({"action": "unknown", "path": temp_file})

        assert "Error" in result
        assert "Unknown action" in result


class TestTaskTool:
    """Tests for TaskTool."""

    @pytest.fixture
    def tool(self):
        return TaskTool()

    def test_create_tasks(self, tool):
        """Test creating a task list."""
        result = tool.run(
            {
                "todos": [
                    {"content": "Task 1", "status": "pending", "activeForm": "Doing task 1"},
                    {"content": "Task 2", "status": "in_progress", "activeForm": "Doing task 2"},
                ]
            }
        )

        assert "Tasks updated" in result
        assert "1 in progress" in result
        assert "1 pending" in result

    def test_update_tasks(self, tool):
        """Test updating task status."""
        # First create tasks
        tool.run(
            {
                "todos": [
                    {"content": "Task 1", "status": "in_progress", "activeForm": "Doing task 1"},
                ]
            }
        )

        # Then update
        result = tool.run(
            {
                "todos": [
                    {"content": "Task 1", "status": "completed", "activeForm": "Doing task 1"},
                ]
            }
        )

        assert "1 completed" in result

    def test_empty_todos(self, tool):
        """Test with empty todo list."""
        result = tool.run({"todos": []})

        assert "No tasks provided" in result

    def test_current_task_display(self, tool):
        """Test current task is shown."""
        result = tool.run(
            {
                "todos": [
                    {"content": "Completed", "status": "completed", "activeForm": "Done"},
                    {
                        "content": "Current",
                        "status": "in_progress",
                        "activeForm": "Working on current",
                    },
                ]
            }
        )

        assert "Current: Working on current" in result
