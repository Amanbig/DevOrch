"""Task schema for tracking work progress."""

from enum import Enum
from typing import Optional, List
from dataclasses import dataclass, field
from datetime import datetime


class TaskStatus(str, Enum):
    """Status of a task."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass
class Task:
    """A single task to track."""
    content: str  # What needs to be done (imperative form)
    status: TaskStatus = TaskStatus.PENDING
    id: Optional[str] = None
    active_form: Optional[str] = None  # Present continuous form (e.g., "Running tests")
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert task to dictionary."""
        return {
            "id": self.id,
            "content": self.content,
            "status": self.status.value,
            "active_form": self.active_form,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        """Create task from dictionary."""
        return cls(
            id=data.get("id"),
            content=data["content"],
            status=TaskStatus(data.get("status", "pending")),
            active_form=data.get("active_form") or data.get("activeForm"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
        )


@dataclass
class TaskList:
    """A list of tasks."""
    tasks: List[Task] = field(default_factory=list)

    def add(self, task: Task) -> Task:
        """Add a task to the list."""
        if not task.id:
            task.id = f"task_{len(self.tasks) + 1}"
        self.tasks.append(task)
        return task

    def get(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def update_status(self, task_id: str, status: TaskStatus) -> Optional[Task]:
        """Update a task's status."""
        task = self.get(task_id)
        if task:
            task.status = status
            if status == TaskStatus.COMPLETED:
                task.completed_at = datetime.now()
        return task

    def get_by_status(self, status: TaskStatus) -> List[Task]:
        """Get all tasks with a specific status."""
        return [t for t in self.tasks if t.status == status]

    def get_current(self) -> Optional[Task]:
        """Get the current in-progress task."""
        in_progress = self.get_by_status(TaskStatus.IN_PROGRESS)
        return in_progress[0] if in_progress else None

    def clear(self):
        """Clear all tasks."""
        self.tasks = []

    @property
    def pending_count(self) -> int:
        return len(self.get_by_status(TaskStatus.PENDING))

    @property
    def in_progress_count(self) -> int:
        return len(self.get_by_status(TaskStatus.IN_PROGRESS))

    @property
    def completed_count(self) -> int:
        return len(self.get_by_status(TaskStatus.COMPLETED))

    @property
    def total_count(self) -> int:
        return len(self.tasks)

    def to_list(self) -> List[dict]:
        """Convert to list of dictionaries."""
        return [t.to_dict() for t in self.tasks]
