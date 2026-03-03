"""
Agent execution modes - controls how DevOrch handles tool execution.

Modes:
- PLAN: Create a plan first, show it, ask for approval, then execute
- AUTO: Execute tools automatically without asking (trusted mode)
- ASK: Ask for confirmation before each tool execution (default)
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class AgentMode(str, Enum):
    PLAN = "plan"  # Plan first, then execute after approval
    AUTO = "auto"  # Execute automatically (no confirmations)
    ASK = "ask"  # Ask before each tool execution (default)


@dataclass
class PlanStep:
    """A single step in an execution plan."""

    description: str
    tool_name: str | None = None
    tool_args: dict | None = None
    status: str = "pending"  # pending, approved, rejected, completed, failed


@dataclass
class ExecutionPlan:
    """A plan of steps to execute."""

    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    approved: bool = False

    def add_step(self, description: str, tool_name: str = None, tool_args: dict = None):
        self.steps.append(
            PlanStep(description=description, tool_name=tool_name, tool_args=tool_args)
        )

    def to_display(self) -> str:
        """Format plan for display."""
        lines = [f"📋 **Plan: {self.goal}**\n"]
        for i, step in enumerate(self.steps, 1):
            status_icon = {
                "pending": "⬜",
                "approved": "✅",
                "rejected": "❌",
                "completed": "✔️",
                "failed": "💥",
            }.get(step.status, "⬜")

            tool_info = f" [{step.tool_name}]" if step.tool_name else ""
            lines.append(f"{status_icon} {i}. {step.description}{tool_info}")

        return "\n".join(lines)


class ModeManager:
    """Manages the current execution mode and plan state."""

    def __init__(self, default_mode: AgentMode = AgentMode.ASK):
        self._mode = default_mode
        self._current_plan: ExecutionPlan | None = None
        self._on_mode_change: Callable[[AgentMode], None] | None = None

    @property
    def mode(self) -> AgentMode:
        return self._mode

    @mode.setter
    def mode(self, value: AgentMode):
        old_mode = self._mode
        self._mode = value
        if self._on_mode_change and old_mode != value:
            self._on_mode_change(value)

    @property
    def current_plan(self) -> ExecutionPlan | None:
        return self._current_plan

    def set_on_mode_change(self, callback: Callable[[AgentMode], None]):
        """Set callback for mode changes."""
        self._on_mode_change = callback

    def start_plan(self, goal: str) -> ExecutionPlan:
        """Start a new execution plan."""
        self._current_plan = ExecutionPlan(goal=goal)
        return self._current_plan

    def clear_plan(self):
        """Clear the current plan."""
        self._current_plan = None

    def approve_plan(self) -> bool:
        """Approve the current plan for execution."""
        if self._current_plan:
            self._current_plan.approved = True
            return True
        return False

    def should_ask_permission(self) -> bool:
        """Check if we should ask for tool permission based on mode."""
        if self._mode == AgentMode.AUTO:
            return False
        elif self._mode == AgentMode.PLAN:
            # In plan mode, don't ask during planning, only during execution
            if self._current_plan and self._current_plan.approved:
                return False  # Plan approved, execute without asking
            return True
        else:  # ASK mode
            return True

    def is_planning(self) -> bool:
        """Check if we're currently in planning phase."""
        return (
            self._mode == AgentMode.PLAN
            and self._current_plan is not None
            and not self._current_plan.approved
        )

    def get_mode_display(self) -> str:
        """Get a short display string for the current mode."""
        mode_displays = {
            AgentMode.PLAN: "[yellow]PLAN[/yellow]",
            AgentMode.AUTO: "[green]AUTO[/green]",
            AgentMode.ASK: "[blue]ASK[/blue]",
        }
        return mode_displays.get(self._mode, str(self._mode))

    def get_mode_description(self) -> str:
        """Get description of current mode."""
        descriptions = {
            AgentMode.PLAN: "Plan mode - I'll show you the plan before executing",
            AgentMode.AUTO: "Auto mode - I'll execute tools automatically",
            AgentMode.ASK: "Ask mode - I'll ask before each tool execution",
        }
        return descriptions.get(self._mode, "")
