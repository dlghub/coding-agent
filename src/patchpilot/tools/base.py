"""
文件名: tools/base.py

功能：
定义工具接口和工具注册表。

设计说明：
每个工具只负责一个明确动作。
ToolRegistry 负责工具查找、统一异常处理和结果截断。
"""

from abc import ABC, abstractmethod
from typing import Any


from patchpilot.schemas import ToolCall, ToolResult



class ToolError(Exception):
    """工具执行异常"""
    pass


class Tool(ABC):
    """工具接口"""

    name: str
    description: str
    parameters: dict[str, Any]

    def definition(self) -> dict[str, Any]:
        """生成发送给模型的 Tool Calling 定义"""

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }

    @abstractmethod
    def execute(self, arguments: dict[str, Any]) -> str:
        """执行工具动作，返回结果字符串"""
        pass


class ToolRegistry:
    """保存, 查询和执行工具的注册表"""

    def __init__(self, tools: list[Tool], max_output_chars: int = 20_000) -> None:
        self._tools: dict[str, Tool] = {}
        self._max_output_chars = max_output_chars

        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"工具名称重复: {tool.name}")

            self._tools[tool.name] = tool


    def definitions(self) -> list[dict[str, Any]]:
        """生成发送给模型的所有工具定义"""
        return [tool.definition() for tool in self._tools.values()]


    def execute(self, call: ToolCall) -> ToolResult:
        """
        执行一次工具调用。

        普通工具错误不会直接终止 Agent, 而是转换成 ToolResult,
        交给模型分析并决定下一步行动。
        """

        tool = self._tools.get(call.name)

        if not tool:
            return ToolResult(
                call_id=call.id,
                tool_name=call.name,
                ok=False,
                output=f"未知工具: {call.name}",
            )

        try:
            output = tool.execute(call.arguments)
            output = self._truncate(output)

            return ToolResult(
                call_id=call.id,
                tool_name=call.name,
                ok=True,
                output=output,
            )
        except Exception as error:
            return ToolResult(
                call_id=call.id,
                tool_name=call.name,
                ok=False,
                output=f"{type(error).__name__}: {error}",
            )

    def _truncate(self, text: str) -> str:
        """截断工具输出, 避免模型被过长输出淹没"""

        if len(text) <= self._max_output_chars:
            return text

        removed = len(text) - self._max_output_chars

        return (
            text[: self._max_output_chars]
            + f"\n\n[输出被截断, 共删除 {removed} 个字符]"
        )