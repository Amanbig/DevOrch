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

from core.agent import Agent
from core.executor import ToolExecutor
from core.modes import AgentMode, ModeManager
from core.planner import Planner
from schemas.message import Message
from tools.base import Tool

SUB_AGENT_SYSTEM_PROMPT = """You are a focused sub-agent inside DevOrch.
Your job is to complete ONE specific task using the tools available to you.
Be direct and efficient. Return a clear, concise result when done.
Do not ask clarifying questions — infer what you can and proceed."""


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

    def __init__(self, provider, tools: list[Tool]):
        self._provider = provider
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

        mode_manager = ModeManager(default_mode=AgentMode.AUTO)
        executor = ToolExecutor(tools=sub_tools, mode_manager=mode_manager)
        planner = SubAgentPlanner()

        sub_agent = Agent(
            provider=self._provider,
            planner=planner,
            executor=executor,
            tools=sub_tools,
            mode_manager=mode_manager,
        )

        return sub_agent.run(task, max_iterations=10)
