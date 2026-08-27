"""
文件名：context.py

功能：
维护 Agent 的对话历史，并保证工具调用与工具结果正确配对。

第一阶段：
仅实现消息保存和工具输出记录。

后续阶段：
可以在本文件中增加 token 预算和历史摘要功能。
"""

from patchpilot.schemas import Message, ModelResponse, ToolResult


class ContextManager:
    """管理一次 Agent 任务的完整对话上下文。"""

    def __init__(self, system_prompt: str) -> None:
        self.system_prompt = system_prompt
        self._messages: list[Message] = []

    def start(self, task: str) -> None:
        """开始一个新任务，并清除上一次任务的上下文。"""

        self._messages = [
            Message(
                role="system",
                content=self.system_prompt,
            ),
            Message(
                role="user",
                content=task,
            ),
        ]

    def add_assistant_response(self, response: ModelResponse) -> None:
        """保存模型返回的文本和工具调用。"""

        self._messages.append(
            Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
        )

    def add_tool_result(self, result: ToolResult) -> None:
        """保存工具执行结果。"""

        status = "成功" if result.ok else "失败"

        self._messages.append(
            Message(
                role="tool",
                tool_call_id=result.call_id,
                content=(
                    f"工具：{result.tool_name}\n"
                    f"状态：{status}\n"
                    f"结果：\n{result.output}"
                ),
            )
        )

    def messages(self) -> list[Message]:
        """
        返回消息副本。

        返回副本可以避免外部代码意外修改内部消息列表。
        """

        return list(self._messages)