"""
文件名：events.py

功能：
定义 Agent 事件接口，并提供测试用空实现和 Rich 终端实现。
"""

import json
from typing import Protocol

from rich.console import Console

from patchpilot.schemas import ToolCall, ToolResult


class EventSink(Protocol):
    """Agent 运行事件接收器接口。"""

    def agent_started(self, task: str) -> None: ...
    def step_started(self, step: int, max_steps: int) -> None: ...
    def tool_started(self, call: ToolCall) -> None: ...
    def tool_finished(self, call: ToolCall, result: ToolResult) -> None: ...
    def agent_finished(self, answer: str) -> None: ...


class NullEventSink:
    """不产生输出的事件接收器，供自动化测试使用。"""

    def agent_started(self, task: str) -> None:
        pass

    def step_started(self, step: int, max_steps: int) -> None:
        pass

    def tool_started(self, call: ToolCall) -> None:
        pass

    def tool_finished(self, call: ToolCall, result: ToolResult) -> None:
        pass

    def agent_finished(self, answer: str) -> None:
        pass


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

    def tool_started(self, call: ToolCall) -> None:
        arguments = dict(call.arguments)
        # 补丁正文可能很长，终端只显示长度，完整参数仍保留在上下文中。
        if call.name == "apply_patch":
            arguments["old_text_chars"] = len(arguments.pop("old_text", ""))
            arguments["new_text_chars"] = len(arguments.pop("new_text", ""))

        self.console.print(f"[yellow]→ 调用工具[/yellow] [bold]{call.name}[/bold]")
        if arguments:
            self.console.print(
                json.dumps(arguments, ensure_ascii=False, indent=2),
                style="dim",
            )

    def tool_finished(self, call: ToolCall, result: ToolResult) -> None:
        style = "green" if result.ok else "red"
        symbol = "✓" if result.ok else "✗"
        self.console.print(f"[{style}]{symbol} {call.name}[/{style}]")
        preview = result.output
        if len(preview) > 2_000:
            preview = preview[:2_000] + "\n[终端预览已截断]"
        self.console.print(preview, style="dim", markup=False, highlight=False)

    def agent_finished(self, answer: str) -> None:
        self.console.print()
        self.console.rule("[bold green]任务完成[/bold green]")
        self.console.print(answer)
