"""
文件名：agent.py

功能：
实现模型调用、工具执行、结果回传和循环终止组成的核心 Agent 循环。
"""

import json
from collections.abc import Callable

from patchpilot.checkpoint import AgentState
from patchpilot.context import ContextManager
from patchpilot.events import EventSink, NullEventSink
from patchpilot.git_review import GitReview
from patchpilot.model import ModelClient
from patchpilot.outcome import EvidenceCollector, RunSummary
from patchpilot.schemas import ToolCall, ToolResult
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
        checkpoint_callback: Callable[[AgentState], None] | None = None,
        git_review_callback: Callable[[], GitReview] | None = None,
    ) -> None:
        if max_steps <= 0:
            raise ValueError("max_steps 必须大于 0")
        self.model = model
        self.context = context
        self.tools = tools
        self.events = events or NullEventSink()
        self.max_steps = max_steps
        self.checkpoint_callback = checkpoint_callback
        self.git_review_callback = git_review_callback
        self.last_summary: RunSummary | None = None

    def run(self, task: str) -> str:
        """执行任务并返回模型的最终回答。"""

        if not task.strip():
            raise ValueError("任务内容不能为空")

        self.context.start(task)
        self.events.agent_started(task)
        failed_calls: dict[str, tuple[int, str]] = {}
        evidence = EvidenceCollector()
        self.last_summary = None

        return self._run_loop(task, failed_calls, evidence)

    def resume(self, state: AgentState) -> str:
        """从磁盘恢复点继续执行，并获得一组新的最大步骤预算。"""

        self.context.restore(state.context)
        failed_calls = {
            key: (int(value[0]), str(value[1]))
            for key, value in state.failed_calls.items()
        }
        evidence = EvidenceCollector.restore(state.evidence)
        self.events.agent_started(f"继续任务：{state.task}")
        self.last_summary = None
        return self._run_loop(state.task, failed_calls, evidence)

    def continue_with(self, task: str) -> str:
        """在保留既有对话上下文的前提下执行一轮新需求。"""

        if not task.strip():
            raise ValueError("任务内容不能为空")
        self.context.add_user_message(task)
        self.events.agent_started(task)
        self.last_summary = None
        return self._run_loop(task, {}, EvidenceCollector())

    def reset_conversation(self) -> None:
        """供交互模式立即开始全新对话。"""

        self.context.clear()
        self.last_summary = None

    def _run_loop(
        self,
        task: str,
        failed_calls: dict[str, tuple[int, str]],
        evidence: EvidenceCollector,
    ) -> str:
        self._save_checkpoint(task, failed_calls, evidence)

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
                    fingerprint = self._tool_call_fingerprint(call)
                    previous_failure = failed_calls.get(fingerprint)
                    if previous_failure is None:
                        result = self.tools.execute(call)
                    else:
                        repeat_count, previous_output = previous_failure
                        repeat_count += 1
                        result = self._duplicate_failure_result(
                            call,
                            repeat_count,
                            previous_output,
                        )

                    if result.ok:
                        failed_calls.pop(fingerprint, None)
                    else:
                        failed_calls[fingerprint] = (
                            result.metadata.get("repeat_count", 1),
                            previous_failure[1]
                            if previous_failure is not None
                            else result.output,
                        )
                    self.context.add_tool_result(result)
                    self.events.tool_finished(call, result)
                    evidence.record(call, result)
                self._save_checkpoint(task, failed_calls, evidence)
                continue

            if response.content and response.content.strip():
                answer = response.content.strip()
                self.events.agent_finished(answer)
                self.last_summary = evidence.build(
                    git_review=self._collect_git_review()
                )
                self.events.run_summary(self.last_summary)
                return answer

            raise RuntimeError("模型返回了空响应")

        message = f"Agent 已达到最大步数 {self.max_steps}，任务仍未结束"
        self.last_summary = evidence.build(
            forced_status="failed",
            extra_warning=message,
            git_review=self._collect_git_review(),
        )
        self.events.run_summary(self.last_summary)
        raise MaxStepsExceeded(message)

    def _collect_git_review(self) -> GitReview | None:
        if self.git_review_callback is None:
            return None
        return self.git_review_callback()

    def _save_checkpoint(
        self,
        task: str,
        failed_calls: dict[str, tuple[int, str]],
        evidence: EvidenceCollector,
    ) -> None:
        if self.checkpoint_callback is None:
            return
        self.checkpoint_callback(
            AgentState(
                task=task,
                context=self.context.snapshot(),
                failed_calls={
                    key: [count, output]
                    for key, (count, output) in failed_calls.items()
                },
                evidence=evidence.snapshot(),
            )
        )

    @staticmethod
    def _tool_call_fingerprint(call: ToolCall) -> str:
        """为工具名和参数生成稳定指纹，忽略每轮变化的调用 ID。"""

        return json.dumps(
            {"name": call.name, "arguments": call.arguments},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=repr,
        )

    @staticmethod
    def _duplicate_failure_result(
        call: ToolCall,
        repeat_count: int,
        previous_output: str,
    ) -> ToolResult:
        """阻止重复执行已失败的完全相同调用，并要求模型改变方案。"""

        return ToolResult(
            call_id=call.id,
            tool_name=call.name,
            ok=False,
            output=(
                f"检测到第 {repeat_count} 次完全相同的失败调用，"
                "为避免重复副作用，本次未再次执行。\n"
                f"首次失败结果：{previous_output}\n"
                "请根据错误修改参数、改用其他工具，或明确说明任务受阻；"
                "不要再次提交相同调用。"
            ),
            metadata={
                "duplicate_failure": True,
                "repeat_count": repeat_count,
            },
        )
