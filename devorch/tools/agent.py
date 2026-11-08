"""
AgentTool — lets the main agent spawn a focused sub-agent for a sub-task.

The sub-agent:
  - Shares the same provider/model as the parent
  - Gets an isolated history (no parent conversation baggage)
  - Runs in AUTO mode (no confirmations)
  - Cannot spawn further sub-agents (no recursion)
  - Is capped at 10 iterations

Typical use-cases the orchestrator delegates:
  - Code review pass on a specific file
  - Running and interpreting tests
  - Writing a commit message after changes are made
  - Fetching + summarising a URL before the parent continues
"""

from typing import Any

from pydantic import BaseModel, Field

from devorch.core.agent import Agent
from devorch.core.executor import ToolExecutor
from devorch.core.modes import AgentMode, ModeManager
from devorch.core.planner import Planner
from devorch.schemas.message import Message
from devorch.tools.base import Tool

SUB_AGENT_SYSTEM_PROMPT = """You are a focused sub-agent inside DevOrch.
Your job is to complete ONE specific task using the tools available to you.
Do only what the task says: do not modify files or run state-changing commands unless the task asks you to.
Look before you answer and never guess file contents or command output.
Be direct and efficient. Return a clear, concise result when done: what you found or did, with file paths.
Do not ask clarifying questions; infer what you can and proceed."""


class SubAgentPlanner(Planner):
    """Minimal planner for sub-agents — lightweight system prompt, no memory injection."""

    def plan(self, history: list[Message]) -> list[Message]:
        return [Message(role="system", content=SUB_AGENT_SYSTEM_PROMPT)] + history


class AgentToolSchema(BaseModel):
    task: str = Field(..., description="The task or question for the sub-agent to complete.")
    tools: list[str] | None = Field(
        default=None,
        description=(
            "Optional list of tool names to give the sub-agent. "
            "If omitted, the sub-agent gets all available tools. "
            "Example: ['shell', 'filesystem', 'grep']"
        ),
    )


class AgentTool(Tool):
    """
    Spawn a focused sub-agent to handle a specific sub-task.

    Use this when:
    - A task is large enough to benefit from isolated context (e.g. review, test, summarise)
    - You want a clean-slate agent that won't be distracted by the main conversation
    - A step requires a specialised tool subset (e.g. only web tools for research)

    The sub-agent runs independently and returns its result as a string.
    It cannot spawn further sub-agents.
    """

    name = "agent"
    description = (
        "Spawn a focused sub-agent to complete a specific sub-task in isolated context. "
        "Use for review passes, test runs, research, or any step that benefits from "
        "a clean slate. The sub-agent returns its result as a string."
    )
    args_schema = AgentToolSchema

    def __init__(self, provider, tools: list[Tool], costs=None, parent_executor=None):
        self._provider = provider
        # The executor of the agent that owns this tool: the sub-agent inherits its permission mode and
        # how permission questions are asked, so approving "agent" does not approve everything inside it
        self.parent_executor = parent_executor
        # Shared with the parent agent so sub-agent calls show up in the session cost
        self.costs = costs
        # Store all tools except this one — sub-agents can't spawn sub-agents
        self._available_tools = [t for t in tools if t.name != "agent"]

    def run(self, arguments: dict[str, Any]) -> str:
        task = arguments["task"]
        requested_tools: list[str] | None = arguments.get("tools")

        # Filter tool set for the sub-agent
        if requested_tools:
            sub_tools = [t for t in self._available_tools if t.name in requested_tools]
            unknown = set(requested_tools) - {t.name for t in sub_tools}
            if unknown:
                sub_tools = self._available_tools  # fall back to all tools on bad names
        else:
            sub_tools = self._available_tools

        parent = self.parent_executor
        parent_mode = parent.mode_manager.mode if parent and parent.mode_manager else AgentMode.AUTO
        # AUTO stays automatic; ASK keeps asking; PLAN (read-only planning) is treated as ASK inside
        mode_manager = ModeManager(
            default_mode=AgentMode.AUTO if parent_mode == AgentMode.AUTO else AgentMode.ASK
        )
        executor = ToolExecutor(tools=sub_tools, mode_manager=mode_manager)
        if parent is not None:
            executor.approver = parent.approver
            executor.permissions = parent.permissions
        planner = SubAgentPlanner()

        sub_agent = Agent(
            provider=self._provider,
            planner=planner,
            executor=executor,
            tools=sub_tools,
            mode_manager=mode_manager,
        )

        if self.costs is not None:
            sub_agent.costs = self.costs
        result = sub_agent.run(task, max_iterations=10)
        if sub_agent.last_run_interrupted:
            # The user pressed Ctrl+C inside the sub-agent: don't hand the parent a normal-looking
            # result and let it carry on; propagate so the whole turn is cancelled.
            raise KeyboardInterrupt
        return result
