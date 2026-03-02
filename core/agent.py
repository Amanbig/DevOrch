from typing import List

from schemas.message import Message
from providers.base import LLMProvider
from core.planner import Planner
from core.executor import Executor


class Agent:
    def __init__(
        self,
        provider: LLMProvider,
        planner: Planner,
        executor: Executor,
        tools: list,
    ):
        self.provider = provider
        self.planner = planner
        self.executor = executor
        self.tools = tools
        self.history: List[Message] = []

    def run(self, user_input: str):
        self.history.append(Message(role="user", content=user_input))

        planned_messages = self.planner.plan(self.history)

        response = self.provider.generate(
            planned_messages,
            tools=[tool.schema() for tool in self.tools],
        )

        self.history.append(response.message)

        if response.tool_calls:
            for call in response.tool_calls:
                result = self.executor.execute(call.name, call.arguments)

                self.history.append(
                    Message(
                        role="tool",
                        content=str(result),
                        name=call.name,
                    )
                )

        return response.message.content