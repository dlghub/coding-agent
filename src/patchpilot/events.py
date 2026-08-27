"""
文件名：events.py

功能：
定义 Agent 运行事件的输出接口。

设计说明：
Agent 只报告发生了什么，不关心这些事件最终显示在终端、
写入日志还是交给测试程序检查。
"""

from typing import Protocol

from patchpilot.schemas import ToolCall, ToolResult


class EventSink(Protocol):
    """Agent 运行事件接收器接口。"""

    def agent_started(self, task: str) -> None:
        ...

    def step_started(self, step: int, max_steps: int) -> None:
        ...

    def tool_started(self, call: ToolCall) -> None:
        ...

    def tool_finished(
        self,
        call: ToolCall,
        result: ToolResult,
    ) -> None:
        ...

    def agent_finished(self, answer: str) -> None:
        ...


class NullEventSink:
    """不输出任何内容的事件接收器，主要用于自动化测试。"""

    def agent_started(self, task: str) -> None:
        pass

    def step_started(self, step: int, max_steps: int) -> None:
        pass

    def tool_started(self, call: ToolCall) -> None:
        pass

    def tool_finished(
        self,
        call: ToolCall,
        result: ToolResult,
    ) -> None:
        pass

    def agent_finished(self, answer: str) -> None:
        pass