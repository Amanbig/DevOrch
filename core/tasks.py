"""Task manager for tracking work progress with visual display."""

from collections.abc import Callable

from rich.console import Console
from rich.live import Live
from rich.panel import Panel

from schemas.task import Task, TaskList, TaskStatus

console = Console()


class TaskManager:
    """Manages tasks and displays progress."""

    def __init__(self, on_update: Callable | None = None):
        self.task_list = TaskList()
        self.on_update = on_update  # Callback when tasks change
        self._live: Live | None = None

    def set_tasks(self, tasks: list[dict]) -> None:
        """Set tasks from a list of dictionaries (from AI tool call)."""
        self.task_list.clear()
        for task_data in tasks:
            task = Task(
                content=task_data["content"],
                status=TaskStatus(task_data.get("status", "pending")),
                active_form=task_data.get("activeForm") or task_data.get("active_form"),
            )
            self.task_list.add(task)
        self._display()

    def add_task(self, content: str, active_form: str | None = None) -> Task:
        """Add a new task."""
        task = Task(content=content, active_form=active_form or content)
        self.task_list.add(task)
        self._display()
        return task

    def start_task(self, task_id: str) -> Task | None:
        """Mark a task as in progress."""
        task = self.task_list.update_status(task_id, TaskStatus.IN_PROGRESS)
        self._display()
        return task

    def complete_task(self, task_id: str) -> Task | None:
        """Mark a task as completed."""
        task = self.task_list.update_status(task_id, TaskStatus.COMPLETED)
        self._display()
        return task

    def get_current_task(self) -> Task | None:
        """Get the currently active task."""
        return self.task_list.get_current()

    def clear_tasks(self) -> None:
        """Clear all tasks."""
        self.task_list.clear()

    def _display(self) -> None:
        """Display the current task list."""
        if self.task_list.total_count == 0:
            return

        panel = self._create_panel()
        console.print(panel)

        if self.on_update:
            self.on_update(self.task_list)

    def _create_panel(self) -> Panel:
        """Create a Rich panel showing task progress."""
        # Build task display
        lines = []

        for task in self.task_list.tasks:
            if task.status == TaskStatus.COMPLETED:
                icon = "[green]✓[/green]"
                style = "dim"
                text = task.content
            elif task.status == TaskStatus.IN_PROGRESS:
                icon = "[cyan]●[/cyan]"
                style = "bold cyan"
                text = task.active_form or task.content
            else:  # PENDING
                icon = "[dim]○[/dim]"
                style = "dim"
                text = task.content

            lines.append(f"  {icon} [{style}]{text}[/{style}]")

        content = "\n".join(lines)

        # Progress info
        completed = self.task_list.completed_count
        total = self.task_list.total_count
        progress = f"{completed}/{total}"

        # Create panel with progress in title
        return Panel(
            content,
            title=f"[bold]Tasks[/bold] [dim]({progress})[/dim]",
            border_style="blue",
            padding=(0, 1),
        )

    def get_status_line(self) -> str:
        """Get a short status line for the current task."""
        current = self.get_current_task()
        if current:
            completed = self.task_list.completed_count
            total = self.task_list.total_count
            return f"[{completed}/{total}] {current.active_form or current.content}"
        return ""

    def to_dict(self) -> dict:
        """Export task list as dictionary."""
        return {
            "tasks": self.task_list.to_list(),
            "completed": self.task_list.completed_count,
            "total": self.task_list.total_count,
        }


# Global task manager instance
_task_manager: TaskManager | None = None


def get_task_manager() -> TaskManager:
    """Get or create the global task manager."""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager


def reset_task_manager() -> TaskManager:
    """Reset and return a new task manager."""
    global _task_manager
    _task_manager = TaskManager()
    return _task_manager
