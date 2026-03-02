"""Tests for core modules (Sessions, Modes, Tasks)."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.modes import AgentMode, ExecutionPlan, ModeManager, PlanStep
from core.tasks import TaskManager, reset_task_manager
from schemas.message import Message
from schemas.task import TaskStatus


class TestAgentMode:
    """Tests for AgentMode enum."""

    def test_mode_values(self):
        """Test AgentMode enum values."""
        assert AgentMode.PLAN.value == "plan"
        assert AgentMode.AUTO.value == "auto"
        assert AgentMode.ASK.value == "ask"

    def test_mode_is_string(self):
        """Test that AgentMode is a string enum."""
        assert AgentMode.PLAN == "plan"
        assert AgentMode.AUTO.value == "auto"


class TestPlanStep:
    """Tests for PlanStep dataclass."""

    def test_create_plan_step(self):
        """Test creating a plan step."""
        step = PlanStep(description="Read the file")
        assert step.description == "Read the file"
        assert step.tool_name is None
        assert step.status == "pending"

    def test_create_step_with_tool(self):
        """Test creating a step with tool info."""
        step = PlanStep(
            description="Search for Python files", tool_name="search", tool_args={"pattern": "*.py"}
        )
        assert step.tool_name == "search"
        assert step.tool_args == {"pattern": "*.py"}


class TestExecutionPlan:
    """Tests for ExecutionPlan dataclass."""

    def test_create_plan(self):
        """Test creating an execution plan."""
        plan = ExecutionPlan(goal="Fix the bug")
        assert plan.goal == "Fix the bug"
        assert plan.steps == []
        assert plan.approved is False

    def test_add_step(self):
        """Test adding steps to plan."""
        plan = ExecutionPlan(goal="Add feature")
        plan.add_step("Read file", tool_name="filesystem")
        plan.add_step("Edit code", tool_name="edit")

        assert len(plan.steps) == 2
        assert plan.steps[0].description == "Read file"
        assert plan.steps[1].tool_name == "edit"

    def test_plan_to_display(self):
        """Test formatting plan for display."""
        plan = ExecutionPlan(goal="Test goal")
        plan.add_step("Step 1", tool_name="tool1")
        plan.add_step("Step 2")

        display = plan.to_display()
        assert "Test goal" in display
        assert "Step 1" in display
        assert "[tool1]" in display
        assert "Step 2" in display


class TestModeManager:
    """Tests for ModeManager class."""

    @pytest.fixture
    def manager(self):
        return ModeManager()

    def test_default_mode(self, manager):
        """Test default mode is ASK."""
        assert manager.mode == AgentMode.ASK

    def test_set_mode(self, manager):
        """Test setting mode."""
        manager.mode = AgentMode.AUTO
        assert manager.mode == AgentMode.AUTO

        manager.mode = AgentMode.PLAN
        assert manager.mode == AgentMode.PLAN

    def test_mode_change_callback(self):
        """Test mode change callback."""
        callback = MagicMock()
        manager = ModeManager()
        manager.set_on_mode_change(callback)

        manager.mode = AgentMode.AUTO
        callback.assert_called_once_with(AgentMode.AUTO)

    def test_mode_change_callback_same_mode(self):
        """Test callback not called when mode unchanged."""
        callback = MagicMock()
        manager = ModeManager(default_mode=AgentMode.ASK)
        manager.set_on_mode_change(callback)

        manager.mode = AgentMode.ASK  # Same as default
        callback.assert_not_called()

    def test_start_plan(self, manager):
        """Test starting a plan."""
        plan = manager.start_plan("Implement feature")
        assert plan is not None
        assert plan.goal == "Implement feature"
        assert manager.current_plan is plan

    def test_clear_plan(self, manager):
        """Test clearing plan."""
        manager.start_plan("Goal")
        assert manager.current_plan is not None

        manager.clear_plan()
        assert manager.current_plan is None

    def test_approve_plan(self, manager):
        """Test approving plan."""
        manager.start_plan("Goal")
        assert not manager.current_plan.approved

        result = manager.approve_plan()
        assert result is True
        assert manager.current_plan.approved

    def test_approve_no_plan(self, manager):
        """Test approving when no plan exists."""
        result = manager.approve_plan()
        assert result is False

    def test_should_ask_permission_auto_mode(self, manager):
        """Test permission check in AUTO mode."""
        manager.mode = AgentMode.AUTO
        assert manager.should_ask_permission() is False

    def test_should_ask_permission_ask_mode(self, manager):
        """Test permission check in ASK mode."""
        manager.mode = AgentMode.ASK
        assert manager.should_ask_permission() is True

    def test_should_ask_permission_plan_mode(self, manager):
        """Test permission check in PLAN mode."""
        manager.mode = AgentMode.PLAN

        # Before plan is approved
        manager.start_plan("Goal")
        assert manager.should_ask_permission() is True

        # After plan is approved
        manager.approve_plan()
        assert manager.should_ask_permission() is False

    def test_is_planning(self, manager):
        """Test is_planning check."""
        manager.mode = AgentMode.PLAN

        # No plan yet
        assert manager.is_planning() is False

        # Plan started
        manager.start_plan("Goal")
        assert manager.is_planning() is True

        # Plan approved
        manager.approve_plan()
        assert manager.is_planning() is False

    def test_get_mode_display(self, manager):
        """Test mode display strings."""
        manager.mode = AgentMode.PLAN
        assert "PLAN" in manager.get_mode_display()

        manager.mode = AgentMode.AUTO
        assert "AUTO" in manager.get_mode_display()

        manager.mode = AgentMode.ASK
        assert "ASK" in manager.get_mode_display()

    def test_get_mode_description(self, manager):
        """Test mode description strings."""
        manager.mode = AgentMode.PLAN
        desc = manager.get_mode_description()
        assert "plan" in desc.lower()

        manager.mode = AgentMode.AUTO
        desc = manager.get_mode_description()
        assert "auto" in desc.lower()


class TestTaskManager:
    """Tests for TaskManager class."""

    @pytest.fixture
    def manager(self):
        """Create a fresh task manager."""
        return reset_task_manager()

    def test_set_tasks(self, manager):
        """Test setting tasks from dictionaries."""
        manager.set_tasks(
            [
                {"content": "Task 1", "status": "pending", "activeForm": "Working on 1"},
                {"content": "Task 2", "status": "in_progress", "activeForm": "Working on 2"},
            ]
        )

        assert manager.task_list.total_count == 2
        assert manager.task_list.pending_count == 1
        assert manager.task_list.in_progress_count == 1

    def test_add_task(self, manager):
        """Test adding a task."""
        task = manager.add_task("New task", "Working on new task")

        assert task.content == "New task"
        assert task.active_form == "Working on new task"
        assert manager.task_list.total_count == 1

    def test_start_task(self, manager):
        """Test starting a task."""
        manager.add_task("Task 1", "Doing task 1")
        task = manager.task_list.tasks[0]

        result = manager.start_task(task.id)
        assert result.status == TaskStatus.IN_PROGRESS

    def test_complete_task(self, manager):
        """Test completing a task."""
        manager.set_tasks([{"content": "Task", "status": "in_progress", "activeForm": "Working"}])
        task = manager.task_list.tasks[0]

        result = manager.complete_task(task.id)
        assert result.status == TaskStatus.COMPLETED
        assert result.completed_at is not None

    def test_get_current_task(self, manager):
        """Test getting current task."""
        manager.set_tasks(
            [
                {"content": "Pending", "status": "pending", "activeForm": "Pending"},
                {"content": "Current", "status": "in_progress", "activeForm": "Current"},
            ]
        )

        current = manager.get_current_task()
        assert current is not None
        assert current.content == "Current"

    def test_get_current_task_none(self, manager):
        """Test getting current task when none active."""
        manager.set_tasks(
            [
                {"content": "Pending", "status": "pending", "activeForm": "Pending"},
            ]
        )

        assert manager.get_current_task() is None

    def test_clear_tasks(self, manager):
        """Test clearing tasks."""
        manager.add_task("Task 1")
        manager.add_task("Task 2")
        assert manager.task_list.total_count == 2

        manager.clear_tasks()
        assert manager.task_list.total_count == 0

    def test_get_status_line(self, manager):
        """Test getting status line."""
        manager.set_tasks(
            [
                {"content": "Done", "status": "completed", "activeForm": "Done"},
                {"content": "Current", "status": "in_progress", "activeForm": "Working on current"},
                {"content": "Next", "status": "pending", "activeForm": "Next"},
            ]
        )

        status = manager.get_status_line()
        assert "[1/3]" in status
        assert "Working on current" in status

    def test_get_status_line_no_current(self, manager):
        """Test status line with no current task."""
        manager.set_tasks(
            [
                {"content": "Pending", "status": "pending", "activeForm": "Pending"},
            ]
        )

        assert manager.get_status_line() == ""

    def test_to_dict(self, manager):
        """Test exporting task list."""
        manager.set_tasks(
            [
                {"content": "Task 1", "status": "completed", "activeForm": "Done 1"},
                {"content": "Task 2", "status": "pending", "activeForm": "Pending 2"},
            ]
        )

        data = manager.to_dict()
        assert data["completed"] == 1
        assert data["total"] == 2
        assert len(data["tasks"]) == 2

    def test_update_callback(self):
        """Test update callback is called."""
        callback = MagicMock()
        manager = TaskManager(on_update=callback)

        manager.set_tasks([{"content": "Task", "status": "pending", "activeForm": "Task"}])

        callback.assert_called_once()


class TestSessionManager:
    """Tests for SessionManager class."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database."""
        from core.sessions import DB_PATH

        # Save original path (used for reference)
        _ = DB_PATH

        # Use temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir) / "test_sessions.db"

            # Patch the DB_PATH
            with patch("core.sessions.DB_PATH", temp_path):
                with patch("core.sessions.DATA_DIR", Path(tmpdir)):
                    yield temp_path

    @pytest.fixture
    def manager(self, temp_db):
        """Create a session manager with temp database."""
        from core.sessions import SessionManager

        with patch("core.sessions.DB_PATH", temp_db):
            with patch("core.sessions.DATA_DIR", temp_db.parent):
                manager = SessionManager()
                yield manager

    def test_create_session(self, manager):
        """Test creating a session."""
        session_id = manager.create_session(provider="openai", model="gpt-4")

        assert session_id is not None
        assert len(session_id) == 8
        assert manager.current_session_id == session_id

    def test_create_session_with_name(self, manager):
        """Test creating a named session."""
        session_id = manager.create_session(
            provider="anthropic", model="claude-3", name="My Session"
        )

        assert session_id is not None

    def test_save_and_load_message(self, manager):
        """Test saving and loading messages."""
        session_id = manager.create_session("openai", "gpt-4")

        # Save messages
        msg1 = Message(role="user", content="Hello")
        msg2 = Message(role="assistant", content="Hi there!")
        manager.save_message(msg1)
        manager.save_message(msg2)

        # Load session
        info, messages = manager.load_session(session_id)

        assert info["provider"] == "openai"
        assert len(messages) == 2
        assert messages[0].content == "Hello"
        assert messages[1].content == "Hi there!"

    def test_save_tool_message(self, manager):
        """Test saving a tool message with metadata."""
        session_id = manager.create_session("openai", "gpt-4")

        msg = Message(
            role="tool",
            content="Result",
            name="shell",
            tool_call_id="call_123",
            metadata={"exit_code": 0},
        )
        manager.save_message(msg)

        info, messages = manager.load_session(session_id)
        assert len(messages) == 1
        assert messages[0].name == "shell"
        assert messages[0].metadata == {"exit_code": 0}

    def test_get_message_count(self, manager):
        """Test getting message count."""
        manager.create_session("openai", "gpt-4")

        assert manager.get_message_count() == 0

        manager.save_message(Message(role="user", content="1"))
        manager.save_message(Message(role="user", content="2"))
        manager.save_message(Message(role="user", content="3"))

        assert manager.get_message_count() == 3

    def test_should_summarize(self, manager):
        """Test summarization check."""
        manager.create_session("openai", "gpt-4")
        manager.message_limit = 3

        assert manager.should_summarize() is False

        for i in range(3):
            manager.save_message(Message(role="user", content=f"Message {i}"))

        assert manager.should_summarize() is True

    def test_list_sessions(self, manager):
        """Test listing sessions."""
        manager.create_session("openai", "gpt-4", name="Session 1")
        manager.create_session("anthropic", "claude", name="Session 2")

        sessions = manager.list_sessions()
        assert len(sessions) >= 2

    def test_delete_session(self, manager):
        """Test deleting a session."""
        session_id = manager.create_session("openai", "gpt-4")
        manager.save_message(Message(role="user", content="Hello"))

        result = manager.delete_session(session_id)
        assert result is True

        assert not manager.session_exists(session_id)

    def test_session_exists(self, manager):
        """Test checking session existence."""
        session_id = manager.create_session("openai", "gpt-4")

        assert manager.session_exists(session_id) is True
        assert manager.session_exists("nonexistent") is False

    def test_load_nonexistent_session(self, manager):
        """Test loading non-existent session."""
        with pytest.raises(ValueError) as exc_info:
            manager.load_session("nonexistent")

        assert "not found" in str(exc_info.value)

    def test_create_continuation_session(self, manager):
        """Test creating a continuation session."""
        first_id = manager.create_session("openai", "gpt-4")
        manager.save_message(Message(role="user", content="Original"))

        new_id = manager.create_continuation_session(
            provider="openai", model="gpt-4", summary="Previous conversation about coding"
        )

        assert new_id != first_id
        assert manager.current_session_id == new_id

    def test_get_session_chain(self, manager):
        """Test getting session chain."""
        first_id = manager.create_session("openai", "gpt-4")

        second_id = manager.create_continuation_session(
            provider="openai", model="gpt-4", summary="Summary 1"
        )

        chain = manager.get_session_chain(second_id)
        assert len(chain) == 2
        assert chain[0]["id"] == first_id
        assert chain[1]["id"] == second_id
