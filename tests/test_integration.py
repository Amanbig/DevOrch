"""Integration tests for DevOrch components working together."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from config.permissions import PermissionLevel, Permissions
from core.executor import ToolExecutor
from core.modes import AgentMode, ModeManager
from core.tasks import reset_task_manager
from tools.edit import EditTool
from tools.filesystem import FilesystemTool
from tools.grep import GrepTool
from tools.search import SearchTool
from tools.task import TaskTool


class TestToolExecutorIntegration:
    """Integration tests for ToolExecutor with various tools."""

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace with test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create project structure
            src = Path(tmpdir) / "src"
            src.mkdir()

            # Main file
            (src / "main.py").write_text("""
def main():
    print("Hello, World!")

if __name__ == "__main__":
    main()
""")

            # Utils file
            (src / "utils.py").write_text("""
def helper():
    return "helper result"

def another_helper():
    return "another"
""")

            # Config file
            (Path(tmpdir) / "config.yaml").write_text("""
name: test-project
version: 1.0.0
""")

            # Test file
            tests = Path(tmpdir) / "tests"
            tests.mkdir()
            (tests / "test_main.py").write_text("""
def test_main():
    assert True
""")

            yield tmpdir

    @pytest.fixture
    def executor(self, temp_workspace):
        """Create an executor with all tools."""
        tools = [
            FilesystemTool(),
            SearchTool(),
            GrepTool(),
            EditTool(),
            TaskTool(),
        ]
        permissions = Permissions()
        # Allow filesystem operations for testing
        permissions.tools["filesystem"] = permissions.tools.get("filesystem", MagicMock())
        permissions.tools["filesystem"].level = PermissionLevel.ALLOW

        mode_manager = ModeManager(default_mode=AgentMode.AUTO)

        return ToolExecutor(
            tools=tools,
            require_confirmation=False,
            permissions=permissions,
            mode_manager=mode_manager,
        )

    def test_read_then_edit_workflow(self, executor, temp_workspace):
        """Test reading a file, then editing it."""
        file_path = os.path.join(temp_workspace, "src", "main.py")

        # First read the file
        read_result = executor.execute("filesystem", {"action": "read", "path": file_path})
        assert "def main" in read_result
        assert "Hello, World!" in read_result

        # Then edit it
        edit_result = executor.execute(
            "edit",
            {
                "action": "replace",
                "path": file_path,
                "find": "Hello, World!",
                "replace_with": "Hello, DevOrch!",
            },
        )
        assert "Replaced" in edit_result

        # Verify the change
        verify_result = executor.execute("filesystem", {"action": "read", "path": file_path})
        assert "Hello, DevOrch!" in verify_result

    def test_search_then_grep_workflow(self, executor, temp_workspace):
        """Test searching for files, then grepping content."""
        # First find Python files
        search_result = executor.execute("search", {"pattern": "*.py", "directory": temp_workspace})
        assert "Found" in search_result
        assert ".py" in search_result

        # Then search for specific content
        grep_result = executor.execute(
            "grep", {"pattern": "def helper", "path": temp_workspace, "include": "*.py"}
        )
        assert "Found" in grep_result
        assert "utils.py" in grep_result

    def test_list_search_read_workflow(self, executor, temp_workspace):
        """Test listing, searching, and reading files."""
        # List the workspace
        list_result = executor.execute("filesystem", {"action": "list", "path": temp_workspace})
        assert "src" in list_result
        assert "tests" in list_result

        # Search for config files
        search_result = executor.execute(
            "search", {"pattern": "*.yaml", "directory": temp_workspace}
        )
        assert "config.yaml" in search_result

        # Read the config
        read_result = executor.execute(
            "filesystem", {"action": "read", "path": os.path.join(temp_workspace, "config.yaml")}
        )
        assert "test-project" in read_result
        assert "version: 1.0.0" in read_result

    def test_create_write_edit_workflow(self, executor, temp_workspace):
        """Test creating, writing, and editing a new file."""
        new_file = os.path.join(temp_workspace, "src", "new_module.py")

        # Create new file
        write_result = executor.execute(
            "filesystem",
            {
                "action": "write",
                "path": new_file,
                "content": """def new_function():
    old_value = 1
    return old_value
""",
            },
        )
        assert "Successfully wrote" in write_result

        # Edit the new file
        edit_result = executor.execute(
            "edit",
            {
                "action": "replace",
                "path": new_file,
                "find": "old_value",
                "replace_with": "new_value",
                "count": 0,  # Replace all
            },
        )
        assert "Replaced" in edit_result

        # Verify changes
        read_result = executor.execute("filesystem", {"action": "read", "path": new_file})
        assert "new_value" in read_result
        assert "old_value" not in read_result

    def test_task_tracking_workflow(self, executor, temp_workspace):
        """Test task tracking during work."""
        # Create initial task list
        task_result = executor.execute(
            "task",
            {
                "todos": [
                    {
                        "content": "Read files",
                        "status": "in_progress",
                        "activeForm": "Reading files",
                    },
                    {"content": "Edit code", "status": "pending", "activeForm": "Editing code"},
                    {
                        "content": "Verify changes",
                        "status": "pending",
                        "activeForm": "Verifying changes",
                    },
                ]
            },
        )
        assert "Tasks updated" in task_result
        assert "1 in progress" in task_result

        # Complete first task, start second
        task_result = executor.execute(
            "task",
            {
                "todos": [
                    {"content": "Read files", "status": "completed", "activeForm": "Reading files"},
                    {"content": "Edit code", "status": "in_progress", "activeForm": "Editing code"},
                    {
                        "content": "Verify changes",
                        "status": "pending",
                        "activeForm": "Verifying changes",
                    },
                ]
            },
        )
        assert "1 completed" in task_result
        assert "1 in progress" in task_result

    def test_unknown_tool(self, executor):
        """Test executing an unknown tool."""
        result = executor.execute("nonexistent_tool", {})
        assert "Error" in result
        assert "not found" in result


class TestModeManagerWithExecutor:
    """Integration tests for ModeManager with Executor."""

    @pytest.fixture
    def tools(self):
        return [FilesystemTool(), SearchTool()]

    def test_auto_mode_no_permission_prompt(self, tools, tmp_path):
        """Test that AUTO mode doesn't prompt for permission."""
        mode_manager = ModeManager(default_mode=AgentMode.AUTO)
        permissions = Permissions()

        executor = ToolExecutor(
            tools=tools,
            require_confirmation=True,  # Would normally require confirmation
            permissions=permissions,
            mode_manager=mode_manager,
        )

        # Should execute without prompting
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        result = executor.execute("filesystem", {"action": "read", "path": str(test_file)})
        assert "content" in result

    def test_ask_mode_checks_permissions(self, tools, tmp_path):
        """Test that ASK mode checks permissions."""
        mode_manager = ModeManager(default_mode=AgentMode.ASK)
        permissions = Permissions()

        # Set filesystem to ALLOW for testing
        permissions.set_tool_permission("filesystem", PermissionLevel.ALLOW)

        executor = ToolExecutor(
            tools=tools,
            require_confirmation=True,
            permissions=permissions,
            mode_manager=mode_manager,
        )

        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        # Should execute because permission is ALLOW
        result = executor.execute("filesystem", {"action": "read", "path": str(test_file)})
        assert "content" in result


class TestTaskManagerIntegration:
    """Integration tests for TaskManager with tools."""

    @pytest.fixture
    def task_manager(self):
        return reset_task_manager()

    def test_task_tool_updates_manager(self, task_manager):
        """Test that TaskTool updates TaskManager."""
        tool = TaskTool()

        tool.run(
            {
                "todos": [
                    {"content": "Task 1", "status": "completed", "activeForm": "Done 1"},
                    {"content": "Task 2", "status": "in_progress", "activeForm": "Doing 2"},
                    {"content": "Task 3", "status": "pending", "activeForm": "Pending 3"},
                ]
            }
        )

        assert task_manager.task_list.total_count == 3
        assert task_manager.task_list.completed_count == 1
        assert task_manager.task_list.in_progress_count == 1
        assert task_manager.task_list.pending_count == 1

    def test_task_manager_current_task(self, task_manager):
        """Test getting current task."""
        tool = TaskTool()

        tool.run(
            {
                "todos": [
                    {"content": "Done", "status": "completed", "activeForm": "Done"},
                    {
                        "content": "Current",
                        "status": "in_progress",
                        "activeForm": "Working on current",
                    },
                ]
            }
        )

        current = task_manager.get_current_task()
        assert current is not None
        assert current.content == "Current"
        assert current.active_form == "Working on current"


class TestEndToEndWorkflow:
    """End-to-end workflow tests."""

    @pytest.fixture
    def workspace(self):
        """Create a realistic project workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create project files
            (Path(tmpdir) / "README.md").write_text("# Test Project\n\nA test project.")

            src = Path(tmpdir) / "src"
            src.mkdir()

            (src / "__init__.py").write_text("")

            (src / "app.py").write_text("""
class App:
    def __init__(self, name):
        self.name = name

    def run(self):
        print(f"Running {self.name}")

    def stop(self):
        print(f"Stopping {self.name}")
""")

            (src / "config.py").write_text("""
DEBUG = True
LOG_LEVEL = "INFO"
MAX_CONNECTIONS = 100
""")

            yield tmpdir

    def test_code_refactoring_workflow(self, workspace):
        """Test a typical code refactoring workflow."""
        tools = [FilesystemTool(), SearchTool(), GrepTool(), EditTool(), TaskTool()]
        permissions = Permissions()
        permissions.set_tool_permission("filesystem", PermissionLevel.ALLOW)
        permissions.set_tool_permission("edit", PermissionLevel.ALLOW)

        executor = ToolExecutor(
            tools=tools,
            require_confirmation=False,
            permissions=permissions,
            mode_manager=ModeManager(default_mode=AgentMode.AUTO),
        )

        # 1. Search for files to refactor
        search_result = executor.execute("search", {"pattern": "*.py", "directory": workspace})
        assert "app.py" in search_result

        # 2. Find the code to change
        grep_result = executor.execute("grep", {"pattern": "class App", "path": workspace})
        assert "Found" in grep_result
        assert "app.py" in grep_result

        # 3. Read the file
        app_path = os.path.join(workspace, "src", "app.py")
        read_result = executor.execute("filesystem", {"action": "read", "path": app_path})
        assert "class App:" in read_result

        # 4. Rename the class
        edit_result = executor.execute(
            "edit",
            {
                "action": "replace",
                "path": app_path,
                "find": "class App:",
                "replace_with": "class Application:",
            },
        )
        assert "Replaced" in edit_result

        # 5. Update references
        edit_result2 = executor.execute(
            "edit",
            {
                "action": "replace",
                "path": app_path,
                "find": "self.name",
                "replace_with": "self._name",
                "count": 0,
            },
        )
        assert "Replaced" in edit_result2

        # 6. Verify changes
        verify_result = executor.execute("filesystem", {"action": "read", "path": app_path})
        assert "class Application:" in verify_result
        assert "self._name" in verify_result
        assert "class App:" not in verify_result

    def test_config_update_workflow(self, workspace):
        """Test updating configuration files."""
        tools = [FilesystemTool(), GrepTool(), EditTool()]
        permissions = Permissions()
        permissions.set_tool_permission("filesystem", PermissionLevel.ALLOW)
        permissions.set_tool_permission("edit", PermissionLevel.ALLOW)

        executor = ToolExecutor(
            tools=tools,
            require_confirmation=False,
            permissions=permissions,
            mode_manager=ModeManager(default_mode=AgentMode.AUTO),
        )

        config_path = os.path.join(workspace, "src", "config.py")

        # 1. Find config values
        grep_result = executor.execute("grep", {"pattern": "DEBUG|LOG_LEVEL", "path": config_path})
        assert "Found" in grep_result

        # 2. Update DEBUG setting
        edit_result = executor.execute(
            "edit",
            {
                "action": "replace",
                "path": config_path,
                "find": "DEBUG = True",
                "replace_with": "DEBUG = False",
            },
        )
        assert "Replaced" in edit_result

        # 3. Update LOG_LEVEL
        edit_result2 = executor.execute(
            "edit",
            {
                "action": "replace",
                "path": config_path,
                "find": 'LOG_LEVEL = "INFO"',
                "replace_with": 'LOG_LEVEL = "WARNING"',
            },
        )
        assert "Replaced" in edit_result2

        # 4. Verify
        verify_result = executor.execute("filesystem", {"action": "read", "path": config_path})
        assert "DEBUG = False" in verify_result
        assert 'LOG_LEVEL = "WARNING"' in verify_result
