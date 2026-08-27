"""
文件名：agent.py

功能：
实现模型调用、工具执行、结果回传和循环终止组成的核心 Agent 循环。
"""

from patchpilot.context import ContextManager
from patchpilot.events import EventSink, NullEventSink
from patchpilot.model import ModelClient
from patchpilot.tools.base import ToolRegistry


class MaxStepsExceeded(Exception):
    """达到最大循环步数但任务尚未正常结束。"""


class Agent:
    """协调模型、上下文、本地工具与运行事件。"""

    def __init__(
        self,
        model: ModelClient,
        context: ContextManager,
        tools: ToolRegistry,
        events: EventSink | None = None,
        max_steps: int = 20,
    ) -> None:
        if max_steps <= 0:
            raise ValueError("max_steps 必须大于 0")
        self.model = model
        self.context = context
        self.tools = tools
        self.events = events or NullEventSink()
        self.max_steps = max_steps

    def run(self, task: str) -> str:
        """执行任务并返回模型的最终回答。"""

        if not task.strip():
            raise ValueError("任务内容不能为空")

        self.context.start(task)
        self.events.agent_started(task)

        for step in range(1, self.max_steps + 1):
            self.events.step_started(step, self.max_steps)
            response = self.model.complete(
                messages=self.context.messages(),
                tools=self.tools.definitions(),
            )
            # assistant 工具调用消息必须先于对应的 tool result 保存。
            self.context.add_assistant_response(response)

            if response.tool_calls:
                for call in response.tool_calls:
                    self.events.tool_started(call)
                    result = self.tools.execute(call)
                    self.context.add_tool_result(result)
                    self.events.tool_finished(call, result)
                continue

            if response.content and response.content.strip():
                answer = response.content.strip()
                self.events.agent_finished(answer)
                return answer

            raise RuntimeError("模型返回了空响应")

        raise MaxStepsExceeded(
            f"Agent 已达到最大步数 {self.max_steps}，任务仍未结束"
        )
