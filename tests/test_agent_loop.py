"""
文件名：test_agent_loop.py

功能：
使用假模型验证 Agent 循环，不调用真实 API，也不消耗 Token。
"""

from collections.abc import Iterable
from typing import Any

import pytest

from patchpilot.agent import Agent, MaxStepsExceeded
from patchpilot.checkpoint import AgentState
from patchpilot.context import ContextManager
from patchpilot.events import NullEventSink
from patchpilot.git_review import GitReview
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


def test_agent_continues_with_existing_conversation_context() -> None:
    model = FakeModelClient(
        [ModelResponse(content="第一次回答"), ModelResponse(content="第二次回答")]
    )
    agent = make_agent(model)

    agent.run("第一次需求")
    answer = agent.continue_with("根据刚才结果继续")

    assert answer == "第二次回答"
    contents = [message.content for message in model.calls[1]]
    assert "第一次需求" in contents
    assert "第一次回答" in contents
    assert contents[-1] == "根据刚才结果继续"


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


def test_agent_does_not_reexecute_identical_failed_call() -> None:
    class CountingFailingTool(RecordingTool):
        name = "fail"

        def __init__(self) -> None:
            super().__init__()
            self.execution_count = 0

        def execute(self, arguments: dict[str, Any]) -> str:
            self.execution_count += 1
            raise RuntimeError("参数无效")

    tool = CountingFailingTool()
    model = FakeModelClient(
        [
            ModelResponse(
                tool_calls=[ToolCall("fail-1", "fail", {"value": "same"})]
            ),
            ModelResponse(
                tool_calls=[ToolCall("fail-2", "fail", {"value": "same"})]
            ),
            ModelResponse(content="已改用其他方案。"),
        ]
    )

    answer = make_agent(model, tool).run("测试重复失败调用")

    assert answer == "已改用其他方案。"
    assert tool.execution_count == 1
    duplicate_message = model.calls[2][-1].content or ""
    assert "完全相同" in duplicate_message
    assert "本次未再次执行" in duplicate_message
    assert "参数无效" in duplicate_message


def test_agent_executes_changed_call_after_failure() -> None:
    class FailsForBadValue(RecordingTool):
        name = "sometimes_fail"

        def execute(self, arguments: dict[str, Any]) -> str:
            self.received.append(arguments)
            if arguments["value"] == "bad":
                raise RuntimeError("参数无效")
            return "ok"

    tool = FailsForBadValue()
    model = FakeModelClient(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall("call-1", "sometimes_fail", {"value": "bad"})
                ]
            ),
            ModelResponse(
                tool_calls=[
                    ToolCall("call-2", "sometimes_fail", {"value": "good"})
                ]
            ),
            ModelResponse(content="修正完成。"),
        ]
    )

    assert make_agent(model, tool).run("修正参数") == "修正完成。"
    assert tool.received == [{"value": "bad"}, {"value": "good"}]


def test_repeated_failure_count_increases_without_reexecution() -> None:
    class CountingFailingTool(RecordingTool):
        name = "always_fail"

        def __init__(self) -> None:
            super().__init__()
            self.execution_count = 0

        def execute(self, arguments: dict[str, Any]) -> str:
            self.execution_count += 1
            raise RuntimeError("始终失败")

    tool = CountingFailingTool()
    repeated_calls = [
        ModelResponse(
            tool_calls=[
                ToolCall(f"call-{index}", "always_fail", {"value": "x"})
            ]
        )
        for index in range(1, 4)
    ]
    model = FakeModelClient([*repeated_calls, ModelResponse(content="停止重复。")])

    make_agent(model, tool).run("测试重复计数")

    assert tool.execution_count == 1
    assert "第 3 次" in (model.calls[3][-1].content or "")


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


def test_agent_resumes_from_checkpoint_with_existing_tool_context() -> None:
    tool = RecordingTool()
    states: list[AgentState] = []
    first_model = FakeModelClient(
        [
            ModelResponse(
                tool_calls=[ToolCall("call-1", "record", {"value": "first"})]
            )
        ]
    )
    first_agent = Agent(
        model=first_model,
        context=ContextManager("system"),
        tools=ToolRegistry([tool]),
        events=NullEventSink(),
        max_steps=1,
        checkpoint_callback=states.append,
    )
    with pytest.raises(MaxStepsExceeded):
        first_agent.run("继续测试")

    resumed_model = FakeModelClient([ModelResponse(content="恢复后完成。")])
    resumed_agent = Agent(
        model=resumed_model,
        context=ContextManager("system"),
        tools=ToolRegistry([tool]),
        events=NullEventSink(),
        max_steps=2,
    )

    answer = resumed_agent.resume(states[-1])

    assert answer == "恢复后完成。"
    received = resumed_model.calls[0]
    assert received[-2].role == "assistant"
    assert received[-1].role == "tool"
    assert received[-1].tool_call_id == "call-1"


def test_agent_rejects_empty_task_and_response() -> None:
    with pytest.raises(ValueError, match="任务内容不能为空"):
        make_agent(FakeModelClient([])).run("   ")

    with pytest.raises(RuntimeError, match="模型返回了空响应"):
        make_agent(FakeModelClient([ModelResponse()])).run("空响应")


def test_summary_requires_verification_after_last_change() -> None:
    class PatchTool(RecordingTool):
        name = "apply_patch"

    class CommandTool(RecordingTool):
        name = "run_command"

        def execute(self, arguments: dict[str, Any]) -> str:
            self.received.append(arguments)
            return "命令：python -m pytest -q\n退出码：0"

    patch = PatchTool()
    command = CommandTool()
    model = FakeModelClient(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "patch-1",
                        "apply_patch",
                        {"path": "app.py", "value": "change"},
                    )
                ]
            ),
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "test-1",
                        "run_command",
                        {"command": ["python", "-m", "pytest", "-q"]},
                    )
                ]
            ),
            ModelResponse(content="全部完成。"),
        ]
    )
    agent = Agent(
        model=model,
        context=ContextManager("system"),
        tools=ToolRegistry([patch, command]),
        events=NullEventSink(),
    )

    agent.run("修改并测试")

    assert agent.last_summary is not None
    assert agent.last_summary.status == "completed"
    assert agent.last_summary.changed_files == ["app.py"]
    assert agent.last_summary.verification_current is True
    assert agent.last_summary.verifications[0].passed is True


def test_summary_marks_change_after_test_as_partial() -> None:
    class PatchTool(RecordingTool):
        name = "apply_patch"

    class CommandTool(RecordingTool):
        name = "run_command"

        def execute(self, arguments: dict[str, Any]) -> str:
            return "命令：pytest -q\n退出码：0"

    model = FakeModelClient(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall("test", "run_command", {"command": ["pytest", "-q"]})
                ]
            ),
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "patch",
                        "apply_patch",
                        {"path": "late.py", "value": "change"},
                    )
                ]
            ),
            ModelResponse(content="我声称已经全部完成。"),
        ]
    )
    agent = Agent(
        model=model,
        context=ContextManager("system"),
        tools=ToolRegistry([PatchTool(), CommandTool()]),
        events=NullEventSink(),
    )

    agent.run("测试后又修改")

    assert agent.last_summary is not None
    assert agent.last_summary.status == "partial"
    assert agent.last_summary.verification_current is False
    assert "最后一次修改" in agent.last_summary.warnings[0]


def test_summary_records_failed_verification() -> None:
    class CommandTool(RecordingTool):
        name = "run_command"

        def execute(self, arguments: dict[str, Any]) -> str:
            return "命令：pytest -q\n退出码：1"

    model = FakeModelClient(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall("test", "run_command", {"command": ["pytest", "-q"]})
                ]
            ),
            ModelResponse(content="完成。"),
        ]
    )
    agent = Agent(
        model=model,
        context=ContextManager("system"),
        tools=ToolRegistry([CommandTool()]),
        events=NullEventSink(),
    )

    agent.run("运行测试")

    assert agent.last_summary is not None
    assert agent.last_summary.status == "partial"
    assert agent.last_summary.verifications[0].passed is False


def test_summary_uses_latest_verification_after_change() -> None:
    class PatchTool(RecordingTool):
        name = "apply_patch"

    class SequencedCommandTool(RecordingTool):
        name = "run_command"

        def __init__(self) -> None:
            super().__init__()
            self.exit_codes = iter([0, 1])

        def execute(self, arguments: dict[str, Any]) -> str:
            return f"命令：pytest -q\n退出码：{next(self.exit_codes)}"

    model = FakeModelClient(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "patch", "apply_patch", {"path": "app.py", "value": "x"}
                    )
                ]
            ),
            ModelResponse(
                tool_calls=[
                    ToolCall("pass", "run_command", {"command": ["pytest", "-q"]})
                ]
            ),
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "fail",
                        "run_command",
                        {"command": ["pytest", "tests/test_app.py", "-q"]},
                    )
                ]
            ),
            ModelResponse(content="完成。"),
        ]
    )
    agent = Agent(
        model=model,
        context=ContextManager("system"),
        tools=ToolRegistry([PatchTool(), SequencedCommandTool()]),
        events=NullEventSink(),
    )

    agent.run("验证最新状态")

    assert agent.last_summary is not None
    assert agent.last_summary.status == "partial"
    assert agent.last_summary.verification_current is False


def test_git_diff_check_failure_downgrades_claimed_completion() -> None:
    model = FakeModelClient([ModelResponse(content="全部完成。")])
    agent = Agent(
        model=model,
        context=ContextManager("system"),
        tools=ToolRegistry([]),
        events=NullEventSink(),
        git_review_callback=lambda: GitReview(
            available=True,
            status_lines=[" M app.py"],
            diff_stat="app.py | 1 +",
            diff_check_passed=False,
        ),
    )

    agent.run("检查项目")

    assert agent.last_summary is not None
    assert agent.last_summary.status == "partial"
    assert "diff --check" in agent.last_summary.warnings[0]
