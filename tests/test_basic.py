"""Basic tests for DevPilot."""

import pytest


def test_imports():
    """Test that main modules can be imported."""
    from schemas.message import Message
    from schemas.task import Task, TaskStatus
    from tools.base import Tool

    assert Message is not None
    assert Task is not None
    assert TaskStatus is not None
    assert Tool is not None


def test_message_creation():
    """Test Message dataclass."""
    from schemas.message import Message

    msg = Message(role="user", content="Hello")
    assert msg.role == "user"
    assert msg.content == "Hello"


def test_task_status_enum():
    """Test TaskStatus enum values."""
    from schemas.task import TaskStatus

    assert TaskStatus.PENDING == "pending"
    assert TaskStatus.IN_PROGRESS == "in_progress"
    assert TaskStatus.COMPLETED == "completed"
