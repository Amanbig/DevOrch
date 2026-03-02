"""Task tool for AI to track work progress."""

from typing import Any

from pydantic import BaseModel, Field

from core.tasks import get_task_manager
from tools.base import Tool


class TaskItem(BaseModel):
    """A single task item."""

    content: str = Field(
        ..., description="What needs to be done (imperative form, e.g., 'Run tests')"
    )
    status: str = Field("pending", description="Task status: pending, in_progress, or completed")
    activeForm: str = Field(
        ..., description="Present continuous form shown during execution (e.g., 'Running tests')"
    )


class TaskToolSchema(BaseModel):
    """Schema for the task tool."""

    todos: list[TaskItem] = Field(..., description="The updated todo list with all tasks")


class TaskTool(Tool):
    """
    Tool for AI to manage a task list and track progress.

    Use this tool to:
    - Create a task list when starting multi-step work
    - Update task status as you complete items
    - Show the user what you're working on

    Guidelines:
    - Only ONE task should be 'in_progress' at a time
    - Mark tasks 'completed' immediately after finishing
    - Content should be imperative (e.g., "Fix bug")
    - ActiveForm should be present continuous (e.g., "Fixing bug")
    """

    name = "task"
    description = """Create and manage a task list to track progress on multi-step work.
Use this when:
- Working on tasks with 3+ steps
- User provides multiple items to do
- You want to show progress to the user

Task status options: pending, in_progress, completed
Only ONE task should be in_progress at a time."""

    args_schema = TaskToolSchema

    def run(self, arguments: dict[str, Any]) -> str:
        """Execute the task tool."""
        todos = arguments.get("todos", [])

        if not todos:
            return "No tasks provided."

        # Convert to list of dicts if needed
        task_list = []
        for item in todos:
            if isinstance(item, dict):
                task_list.append(item)
            else:
                # Pydantic model
                task_list.append(
                    {
                        "content": item.content,
                        "status": item.status,
                        "activeForm": item.activeForm,
                    }
                )

        # Update task manager
        task_manager = get_task_manager()
        task_manager.set_tasks(task_list)

        # Return summary
        completed = sum(1 for t in task_list if t.get("status") == "completed")
        in_progress = sum(1 for t in task_list if t.get("status") == "in_progress")
        pending = sum(1 for t in task_list if t.get("status") == "pending")

        current = next((t for t in task_list if t.get("status") == "in_progress"), None)
        current_text = f" Current: {current['activeForm']}" if current else ""

        return f"Tasks updated: {completed} completed, {in_progress} in progress, {pending} pending.{current_text}"
