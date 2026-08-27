"""
文件名：tools/base.py

功能：
定义工具接口、工具注册表和统一审批边界。
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from patchpilot.schemas import ToolCall, ToolResult


class ToolError(Exception):
    """工具执行过程中出现的可恢复错误。"""


class Tool(ABC):
    """所有本地工具的抽象基类。"""

    name: str
    description: str
    parameters: dict[str, Any]

    def definition(self) -> dict[str, Any]:
        """生成发送给模型的 Tool Calling 定义。"""

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @abstractmethod
    def execute(self, arguments: dict[str, Any]) -> str:
        """执行工具并返回适合发送给模型的文本。"""


ApprovalCallback = Callable[[ToolCall], bool]


class ToolRegistry:
    """保存、审批并执行全部可用工具。"""

    def __init__(
        self,
        tools: list[Tool],
        max_output_chars: int = 20_000,
        approval: ApprovalCallback | None = None,
    ) -> None:
        if max_output_chars <= 0:
            raise ValueError("max_output_chars 必须大于 0")
        self._tools: dict[str, Tool] = {}
        self._max_output_chars = max_output_chars
        self._approval = approval
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"工具名称重复：{tool.name}")
            self._tools[tool.name] = tool

    def definitions(self) -> list[dict[str, Any]]:
        """返回全部工具的模型接口定义。"""

        return [tool.definition() for tool in self._tools.values()]

    def execute(self, call: ToolCall) -> ToolResult:
        """审批并执行工具；失败转换为 ToolResult 供模型恢复。"""

        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(call.id, call.name, False, f"未知工具：{call.name}")

        try:
            if self._approval is not None and not self._approval(call):
                return ToolResult(
                    call.id,
                    call.name,
                    False,
                    "用户拒绝了本次工具调用；请停止该操作或采用安全替代方案。",
                )
            output = self._truncate(tool.execute(call.arguments))
            return ToolResult(call.id, call.name, True, output)
        except Exception as error:
            return ToolResult(
                call.id,
                call.name,
                False,
                f"{type(error).__name__}: {error}",
            )

    def _truncate(self, text: str) -> str:
        """截断超长输出，避免工具结果占满模型上下文。"""

        if len(text) <= self._max_output_chars:
            return text
        removed = len(text) - self._max_output_chars
        return text[: self._max_output_chars] + f"\n\n[输出已截断，省略 {removed} 个字符]"
