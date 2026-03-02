"""Tests for schema dataclasses and models."""

from datetime import datetime

from schemas.message import LLMResponse, Message, ToolCall
from schemas.task import Task, TaskList, TaskStatus


class TestMessage:
    """Tests for Message dataclass."""

    def test_create_user_message(self):
        """Test creating a basic user message."""
        msg = Message(role="user", content="Hello, world!")
        assert msg.role == "user"
        assert msg.content == "Hello, world!"
        assert msg.name is None
        assert msg.tool_call_id is None
        assert msg.metadata is None

    def test_create_assistant_message(self):
        """Test creating an assistant message."""
        msg = Message(role="assistant", content="Hi there!")
        assert msg.role == "assistant"
        assert msg.content == "Hi there!"

    def test_create_tool_message(self):
        """Test creating a tool message with all fields."""
        msg = Message(
            role="tool",
            content="Command executed successfully",
            name="shell",
            tool_call_id="call_123",
        )
        assert msg.role == "tool"
        assert msg.name == "shell"
        assert msg.tool_call_id == "call_123"

    def test_message_with_metadata(self):
        """Test message with metadata."""
        metadata = {"tool_calls": [{"id": "call_1", "name": "shell"}]}
        msg = Message(role="assistant", content="Let me run that", metadata=metadata)
        assert msg.metadata == metadata
        assert msg.metadata["tool_calls"][0]["id"] == "call_1"


class TestToolCall:
    """Tests for ToolCall dataclass."""

    def test_create_tool_call(self):
        """Test creating a tool call."""
        call = ToolCall(name="shell", arguments={"command": "ls -la"})
        assert call.name == "shell"
        assert call.arguments == {"command": "ls -la"}
        assert call.id is None

    def test_tool_call_with_id(self):
        """Test tool call with ID."""
        call = ToolCall(
            name="filesystem", arguments={"action": "read", "path": "test.py"}, id="call_abc"
        )
        assert call.id == "call_abc"

    def test_tool_call_empty_arguments(self):
        """Test tool call with empty arguments."""
        call = ToolCall(name="test", arguments={})
        assert call.arguments == {}


class TestLLMResponse:
    """Tests for LLMResponse dataclass."""

    def test_response_without_tool_calls(self):
        """Test LLM response with just a message."""
        msg = Message(role="assistant", content="Here's my answer")
        response = LLMResponse(message=msg)
        assert response.message.content == "Here's my answer"
        assert response.tool_calls is None
        assert response.raw is None

    def test_response_with_tool_calls(self):
        """Test LLM response with tool calls."""
        msg = Message(role="assistant", content="Let me search for that")
        tool_calls = [
            ToolCall(name="search", arguments={"pattern": "*.py"}, id="call_1"),
            ToolCall(name="grep", arguments={"pattern": "def test"}, id="call_2"),
        ]
        response = LLMResponse(message=msg, tool_calls=tool_calls)
        assert len(response.tool_calls) == 2
        assert response.tool_calls[0].name == "search"
        assert response.tool_calls[1].name == "grep"

    def test_response_with_raw(self):
        """Test LLM response with raw data."""
        msg = Message(role="assistant", content="Response")
        raw_data = {"model": "gpt-4", "usage": {"tokens": 100}}
        response = LLMResponse(message=msg, raw=raw_data)
        assert response.raw["model"] == "gpt-4"


class TestTaskStatus:
    """Tests for TaskStatus enum."""

    def test_task_status_values(self):
        """Test TaskStatus enum values."""
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.IN_PROGRESS.value == "in_progress"
        assert TaskStatus.COMPLETED.value == "completed"

    def test_task_status_is_string_enum(self):
        """Test that TaskStatus is a string enum."""
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.PENDING.value == "pending"


class TestTask:
    """Tests for Task dataclass."""

    def test_create_task(self):
        """Test creating a basic task."""
        task = Task(content="Fix the bug")
        assert task.content == "Fix the bug"
        assert task.status == TaskStatus.PENDING
        assert task.id is None
        assert task.active_form is None

    def test_create_task_with_active_form(self):
        """Test creating a task with active form."""
        task = Task(content="Run tests", status=TaskStatus.IN_PROGRESS, active_form="Running tests")
        assert task.content == "Run tests"
        assert task.active_form == "Running tests"
        assert task.status == TaskStatus.IN_PROGRESS

    def test_task_to_dict(self):
        """Test converting task to dictionary."""
        task = Task(
            content="Write code",
            status=TaskStatus.COMPLETED,
            id="task_1",
            active_form="Writing code",
        )
        data = task.to_dict()
        assert data["id"] == "task_1"
        assert data["content"] == "Write code"
        assert data["status"] == "completed"
        assert data["active_form"] == "Writing code"
        assert "created_at" in data

    def test_task_from_dict(self):
        """Test creating task from dictionary."""
        data = {
            "id": "task_2",
            "content": "Review PR",
            "status": "in_progress",
            "activeForm": "Reviewing PR",
            "created_at": datetime.now().isoformat(),
        }
        task = Task.from_dict(data)
        assert task.id == "task_2"
        assert task.content == "Review PR"
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.active_form == "Reviewing PR"

    def test_task_from_dict_minimal(self):
        """Test creating task from minimal dictionary."""
        data = {"content": "Simple task"}
        task = Task.from_dict(data)
        assert task.content == "Simple task"
        assert task.status == TaskStatus.PENDING


class TestTaskList:
    """Tests for TaskList dataclass."""

    def test_empty_task_list(self):
        """Test empty task list."""
        tl = TaskList()
        assert tl.tasks == []
        assert tl.total_count == 0
        assert tl.pending_count == 0
        assert tl.in_progress_count == 0
        assert tl.completed_count == 0

    def test_add_task(self):
        """Test adding tasks."""
        tl = TaskList()
        task = Task(content="First task")
        result = tl.add(task)
        assert result.id is not None
        assert len(tl.tasks) == 1
        assert tl.total_count == 1

    def test_add_task_preserves_id(self):
        """Test that adding a task with ID preserves it."""
        tl = TaskList()
        task = Task(content="Task", id="custom_id")
        tl.add(task)
        assert tl.tasks[0].id == "custom_id"

    def test_get_task(self):
        """Test getting a task by ID."""
        tl = TaskList()
        task = Task(content="Find me", id="findable")
        tl.add(task)
        found = tl.get("findable")
        assert found is not None
        assert found.content == "Find me"

    def test_get_task_not_found(self):
        """Test getting a non-existent task."""
        tl = TaskList()
        assert tl.get("nonexistent") is None

    def test_update_status(self):
        """Test updating task status."""
        tl = TaskList()
        task = Task(content="Update me", id="updatable")
        tl.add(task)

        result = tl.update_status("updatable", TaskStatus.IN_PROGRESS)
        assert result.status == TaskStatus.IN_PROGRESS

        result = tl.update_status("updatable", TaskStatus.COMPLETED)
        assert result.status == TaskStatus.COMPLETED
        assert result.completed_at is not None

    def test_get_by_status(self):
        """Test getting tasks by status."""
        tl = TaskList()
        tl.add(Task(content="Pending 1", id="p1"))
        tl.add(Task(content="Pending 2", id="p2"))
        tl.add(Task(content="In Progress", id="ip", status=TaskStatus.IN_PROGRESS))
        tl.add(Task(content="Done", id="d", status=TaskStatus.COMPLETED))

        pending = tl.get_by_status(TaskStatus.PENDING)
        assert len(pending) == 2

        in_progress = tl.get_by_status(TaskStatus.IN_PROGRESS)
        assert len(in_progress) == 1

        completed = tl.get_by_status(TaskStatus.COMPLETED)
        assert len(completed) == 1

    def test_get_current(self):
        """Test getting the current in-progress task."""
        tl = TaskList()
        tl.add(Task(content="Pending"))
        assert tl.get_current() is None

        tl.add(Task(content="Current", status=TaskStatus.IN_PROGRESS))
        current = tl.get_current()
        assert current is not None
        assert current.content == "Current"

    def test_clear(self):
        """Test clearing all tasks."""
        tl = TaskList()
        tl.add(Task(content="Task 1"))
        tl.add(Task(content="Task 2"))
        assert tl.total_count == 2

        tl.clear()
        assert tl.total_count == 0
        assert tl.tasks == []

    def test_counts(self):
        """Test task count properties."""
        tl = TaskList()
        tl.add(Task(content="P1"))
        tl.add(Task(content="P2"))
        tl.add(Task(content="IP", status=TaskStatus.IN_PROGRESS))
        tl.add(Task(content="C1", status=TaskStatus.COMPLETED))
        tl.add(Task(content="C2", status=TaskStatus.COMPLETED))

        assert tl.pending_count == 2
        assert tl.in_progress_count == 1
        assert tl.completed_count == 2
        assert tl.total_count == 5

    def test_to_list(self):
        """Test converting task list to list of dicts."""
        tl = TaskList()
        tl.add(Task(content="Task 1", id="t1"))
        tl.add(Task(content="Task 2", id="t2"))

        result = tl.to_list()
        assert len(result) == 2
        assert result[0]["id"] == "t1"
        assert result[1]["id"] == "t2"
