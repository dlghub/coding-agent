"""
文件名：events.py

功能：
定义 Agent 事件接口、终端展示、组合分发和 JSONL 会话日志。
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from rich.console import Console

from patchpilot.schemas import ToolCall, ToolResult
from patchpilot.outcome import RunSummary


def safe_tool_arguments(call: ToolCall) -> dict:
    """移除补丁正文等不适合展示或记录的大字段。"""

    arguments = dict(call.arguments)
    if call.name == "apply_patch":
        arguments["old_text_chars"] = len(arguments.pop("old_text", ""))
        arguments["new_text_chars"] = len(arguments.pop("new_text", ""))
    return arguments


class EventSink(Protocol):
    def agent_started(self, task: str) -> None: ...
    def step_started(self, step: int, max_steps: int) -> None: ...
    def model_retrying(
        self, attempt: int, max_attempts: int, reason: str, delay: float
    ) -> None: ...
    def tool_started(self, call: ToolCall) -> None: ...
    def tool_finished(self, call: ToolCall, result: ToolResult) -> None: ...
    def agent_finished(self, answer: str) -> None: ...
    def run_summary(self, summary: RunSummary) -> None: ...


class NullEventSink:
    def agent_started(self, task: str) -> None: pass
    def step_started(self, step: int, max_steps: int) -> None: pass
    def model_retrying(
        self, attempt: int, max_attempts: int, reason: str, delay: float
    ) -> None: pass
    def tool_started(self, call: ToolCall) -> None: pass
    def tool_finished(self, call: ToolCall, result: ToolResult) -> None: pass
    def agent_finished(self, answer: str) -> None: pass
    def run_summary(self, summary: RunSummary) -> None: pass


class CompositeEventSink:
    """把同一事件分发给多个接收器。"""

    def __init__(self, sinks: list[EventSink]) -> None:
        self.sinks = sinks

    def agent_started(self, task: str) -> None:
        for sink in self.sinks: sink.agent_started(task)

    def step_started(self, step: int, max_steps: int) -> None:
        for sink in self.sinks: sink.step_started(step, max_steps)

    def model_retrying(
        self, attempt: int, max_attempts: int, reason: str, delay: float
    ) -> None:
        for sink in self.sinks:
            sink.model_retrying(attempt, max_attempts, reason, delay)

    def tool_started(self, call: ToolCall) -> None:
        for sink in self.sinks: sink.tool_started(call)

    def tool_finished(self, call: ToolCall, result: ToolResult) -> None:
        for sink in self.sinks: sink.tool_finished(call, result)

    def agent_finished(self, answer: str) -> None:
        for sink in self.sinks: sink.agent_finished(answer)

    def run_summary(self, summary: RunSummary) -> None:
        for sink in self.sinks: sink.run_summary(summary)


class JsonlEventSink:
    """把结构化事件写入权限受限的 JSONL 文件。"""

    def __init__(
        self,
        workspace: Path,
        read_only: bool,
        directory: Path | None = None,
        max_result_chars: int = 4_000,
    ) -> None:
        self.directory = directory or (
            Path.home() / ".local" / "state" / "patchpilot" / "sessions"
        )
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        self.session_id = uuid4().hex
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = self.directory / f"{timestamp}-{self.session_id[:8]}.jsonl"
        self.max_result_chars = max_result_chars
        self._write("session_created", workspace=str(workspace), read_only=read_only)

    def agent_started(self, task: str) -> None:
        self._write("agent_started", task=task)

    def step_started(self, step: int, max_steps: int) -> None:
        self._write("step_started", step=step, max_steps=max_steps)

    def model_retrying(
        self, attempt: int, max_attempts: int, reason: str, delay: float
    ) -> None:
        self._write(
            "model_retrying",
            attempt=attempt,
            max_attempts=max_attempts,
            reason=reason,
            delay_seconds=delay,
        )

    def tool_started(self, call: ToolCall) -> None:
        self._write(
            "tool_started",
            call_id=call.id,
            tool=call.name,
            arguments=safe_tool_arguments(call),
        )

    def tool_finished(self, call: ToolCall, result: ToolResult) -> None:
        output = result.output[: self.max_result_chars]
        self._write(
            "tool_finished",
            call_id=call.id,
            tool=call.name,
            ok=result.ok,
            output=output,
            output_truncated=len(result.output) > len(output),
        )

    def agent_finished(self, answer: str) -> None:
        self._write("agent_finished", answer=answer)

    def run_summary(self, summary: RunSummary) -> None:
        self._write("run_summary", **summary.to_dict())

    def _write(self, event: str, **payload: object) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "event": event,
            **payload,
        }
        descriptor = os.open(
            self.path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


class RichEventSink:
    """使用 Rich 展示 Agent 的运行过程。"""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def agent_started(self, task: str) -> None:
        self.console.print("\n[bold cyan]PatchPilot 开始执行任务[/bold cyan]")
        self.console.print(f"[dim]任务：{task}[/dim]")

    def step_started(self, step: int, max_steps: int) -> None:
        self.console.print()
        self.console.rule(f"[bold blue]Step {step}/{max_steps}[/bold blue]")

    def model_retrying(
        self, attempt: int, max_attempts: int, reason: str, delay: float
    ) -> None:
        self.console.print(
            f"模型响应异常（{reason}），{delay:g} 秒后进行第 "
            f"{attempt}/{max_attempts} 次尝试……",
            style="yellow",
            markup=False,
        )

    def tool_started(self, call: ToolCall) -> None:
        arguments = safe_tool_arguments(call)
        self.console.print(f"[yellow]→ 调用工具[/yellow] [bold]{call.name}[/bold]")
        if arguments:
            self.console.print(json.dumps(arguments, ensure_ascii=False, indent=2), style="dim")

    def tool_finished(self, call: ToolCall, result: ToolResult) -> None:
        style = "green" if result.ok else "red"
        symbol = "✓" if result.ok else "✗"
        self.console.print(f"[{style}]{symbol} {call.name}[/{style}]")
        preview = result.output[:2_000]
        if len(result.output) > len(preview):
            preview += "\n[终端预览已截断]"
        self.console.print(preview, style="dim", markup=False, highlight=False)

    def agent_finished(self, answer: str) -> None:
        self.console.print()
        self.console.rule("[bold green]任务完成[/bold green]")
        self.console.print(answer)

    def run_summary(self, summary: RunSummary) -> None:
        labels = {
            "completed": "已完成",
            "partial": "部分完成",
            "failed": "失败",
        }
        styles = {
            "completed": "green",
            "partial": "yellow",
            "failed": "red",
        }
        self.console.print()
        self.console.rule("[bold]执行证据[/bold]")
        self.console.print(
            f"可信状态：{labels[summary.status]}",
            style=styles[summary.status],
        )
        if summary.changed_files:
            self.console.print(
                "修改文件：" + "、".join(summary.changed_files),
                markup=False,
            )
        else:
            self.console.print("修改文件：无")
        if summary.verifications:
            for evidence in summary.verifications:
                symbol = "✓" if evidence.passed else "✗"
                command = " ".join(evidence.command)
                self.console.print(f"{symbol} {command}", markup=False)
        else:
            self.console.print("验证命令：未运行")
        for warning in summary.warnings:
            self.console.print(f"警告：{warning}", style="yellow", markup=False)
        review = summary.git_review
        if review and review.available:
            self.console.print("Git 工作树：")
            if review.status_lines:
                for line in review.status_lines:
                    self.console.print(f"  {line}", markup=False)
            else:
                self.console.print("  clean")
            if review.diff_stat:
                self.console.print(review.diff_stat, style="dim", markup=False)
            if review.diff_check_passed is not None:
                symbol = "✓" if review.diff_check_passed else "✗"
                self.console.print(f"{symbol} git diff --check", markup=False)
