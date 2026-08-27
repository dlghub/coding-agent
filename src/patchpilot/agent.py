"""
文件名：agent.py

功能：
实现 PatchPilot 的核心 Agent 循环。

核心流程：
1. 将用户任务加入上下文；
2. 调用模型；
3. 解析模型发起的工具调用；
4. 在本地执行工具；
5. 将工具结果返回模型；
6. 重复上述过程，直到模型给出最终回答或达到步数限制。
"""

from patchpilot.context import ContextManager
from patchpilot.events import EventSink, NullEventSink
from patchpilot.model import ModelClient
from patchpilot.tools.base import ToolRegistry


class MaxStepsExceeded(Exception):
    """达到最大步数限制"""
    pass


class Agent:

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
        """执行 Agent 循环，返回最终回答"""

        if not task.strip():
            raise ValueError("任务描述不能为空")

        self.context.start(task)
        self.events.agent_started(task)

        for step in range(1, self.max_steps + 1):
            self.events.step_started(step, self.max_steps)

            # 调用模型
            response = self.model.complete(
                messages=self.context.messages,
                tools=self.tools.definitions(),
            )

            # 必须先保存 assistant 工具调用消息, 再保存 tool result
            self.context.add_assistant_response(response)

            if response.tool_calls:
                for call in response.tool_calls:
                    self.events.tool_started(call)

                    result = self.tools.execute(call)
                    self.context.add_tool_result(result)

                    self.events.tool_finished(call, result)

                # 工具执行完成后进入下一轮, 让模型读取工具结果
                continue

            # 没有工具调用时, 说明模型已经给出最终回答
            if response.content and response.content.strip():
                answer = response.content.strip()
                self.events.agent_finished(answer)
                return answer

            # 模型既没有调用工具, 也没有输出文本, 属于协议异常
            raise RuntimeError("模型返回了空响应")

        raise MaxStepsExceeded(
            f"Agent 达到最大步数限制 ({self.max_steps})，仍未给出最终回答"
        )