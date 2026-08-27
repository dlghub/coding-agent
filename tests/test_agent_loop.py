"""
文件名：test_agent_loop.py

功能：
使用假模型验证 Agent 循环，不调用真实 API，也不消耗 Token。
"""

from collections.abc import Iterable
from typing import Any

import pytest

from patchpilot.agent import Agent, MaxStepsExceeded
from patchpilot.context import ContextManager
from patchpilot.events import NullEventSink
from patchpilot.schemas import Message, ModelResponse, ToolCall
from patchpilot.tools.base import Tool, ToolRegistry


class FakeModelClient:
    """按顺序返回预设响应，并记录每次收到的消息。"""

    def __init__(self, responses: Iterable[ModelResponse]) -> None:
        self._responses = iter(responses)
        self.calls: list[list[Message]] = []

    def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        self.calls.append(list(messages))
        return next(self._responses)


class RecordingTool(Tool):
    """记录参数并返回固定结果的测试工具。"""

    name = "record"
    description = "Record a value for testing."
    parameters = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    }

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []

    def execute(self, arguments: dict[str, Any]) -> str:
        self.received.append(arguments)
        return f"recorded: {arguments['value']}"


def make_agent(
    model: FakeModelClient,
    tool: Tool | None = None,
    max_steps: int = 10,
) -> Agent:
    return Agent(
        model=model,
        context=ContextManager("test system prompt"),
        tools=ToolRegistry([tool] if tool else []),
        events=NullEventSink(),
        max_steps=max_steps,
    )


def test_agent_returns_direct_answer() -> None:
    model = FakeModelClient([ModelResponse(content="任务完成。")])
    answer = make_agent(model).run("检查项目")
    assert answer == "任务完成。"
    assert model.calls[0][1].content == "检查项目"


def test_agent_executes_tool_and_returns_result_to_model() -> None:
    tool = RecordingTool()
    model = FakeModelClient(
        [
            ModelResponse(
                tool_calls=[ToolCall("call-1", "record", {"value": "hello"})]
            ),
            ModelResponse(content="工具调用完成。"),
        ]
    )
    answer = make_agent(model, tool).run("调用工具")
    assert answer == "工具调用完成。"
    assert tool.received == [{"value": "hello"}]
    assert model.calls[1][-2].role == "assistant"
    assert model.calls[1][-1].role == "tool"
    assert model.calls[1][-1].tool_call_id == "call-1"
    assert "recorded: hello" in (model.calls[1][-1].content or "")


def test_unknown_tool_is_returned_as_error() -> None:
    model = FakeModelClient(
        [
            ModelResponse(tool_calls=[ToolCall("bad-1", "missing", {})]),
            ModelResponse(content="工具不存在。"),
        ]
    )
    assert make_agent(model).run("调用未知工具") == "工具不存在。"
    assert "未知工具" in (model.calls[1][-1].content or "")


def test_tool_exception_does_not_crash_agent() -> None:
    class FailingTool(RecordingTool):
        name = "fail"

        def execute(self, arguments: dict[str, Any]) -> str:
            raise RuntimeError("模拟错误")

    model = FakeModelClient(
        [
            ModelResponse(tool_calls=[ToolCall("fail-1", "fail", {"value": "x"})]),
            ModelResponse(content="已识别工具失败。"),
        ]
    )
    assert make_agent(model, FailingTool()).run("测试失败") == "已识别工具失败。"
    assert "模拟错误" in (model.calls[1][-1].content or "")


def test_agent_stops_at_max_steps() -> None:
    tool = RecordingTool()
    model = FakeModelClient(
        [
            ModelResponse(tool_calls=[ToolCall("call-1", "record", {"value": "1"})]),
            ModelResponse(tool_calls=[ToolCall("call-2", "record", {"value": "2"})]),
        ]
    )
    with pytest.raises(MaxStepsExceeded, match="最大步数 2"):
        make_agent(model, tool, max_steps=2).run("持续调用")


def test_agent_rejects_empty_task_and_response() -> None:
    with pytest.raises(ValueError, match="任务内容不能为空"):
        make_agent(FakeModelClient([])).run("   ")

    with pytest.raises(RuntimeError, match="模型返回了空响应"):
        make_agent(FakeModelClient([ModelResponse()])).run("空响应")
