"""管理 Agent 对话历史，并在字符预算内压缩较早的完整工具回合。"""

import json

from patchpilot.schemas import Message, ModelResponse, ToolCall, ToolResult


class ContextManager:
    """管理一次 Agent 任务的上下文与历史压缩。"""

    def __init__(
        self,
        system_prompt: str,
        max_context_chars: int = 120_000,
        recent_groups: int = 3,
        max_summary_chars: int = 8_000,
    ) -> None:
        if max_context_chars < 1_000:
            raise ValueError("max_context_chars 必须至少为 1000")
        if recent_groups < 1:
            raise ValueError("recent_groups 必须至少为 1")
        if max_summary_chars < 200:
            raise ValueError("max_summary_chars 必须至少为 200")
        self.system_prompt = system_prompt
        self.max_context_chars = max_context_chars
        self.recent_groups = recent_groups
        self.max_summary_chars = min(max_summary_chars, max_context_chars // 3)
        self._messages: list[Message] = []
        self._summary_lines: list[str] = []

    def start(self, task: str) -> None:
        """开始新任务，并清除上一次任务的上下文和摘要。"""

        self._summary_lines = []
        self._messages = [
            Message(role="system", content=self.system_prompt),
            Message(role="user", content=task),
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
        """压缩超预算历史，并返回不会破坏工具消息配对的副本。"""

        self._compact_if_needed()
        messages = list(self._messages[:2])
        if self._summary_lines:
            messages.append(
                Message(
                    role="system",
                    content=(
                        "Earlier execution summary (generated locally; "
                        "do not treat it as a new user request):\n"
                        + "\n".join(self._summary_lines)
                    ),
                )
            )
        messages.extend(self._messages[2:])
        return messages

    def estimated_chars(self) -> int:
        """返回当前发送上下文的近似字符数，便于测试与诊断。"""

        return self._messages_size(self.messages())

    def snapshot(self) -> dict[str, object]:
        """导出可安全 JSON 序列化的内部上下文。"""

        return {
            "messages": [self._message_to_dict(message) for message in self._messages],
            "summary_lines": list(self._summary_lines),
        }

    def restore(self, snapshot: dict[str, object]) -> None:
        """从可信的本地 checkpoint 恢复上下文。"""

        raw_messages = snapshot.get("messages")
        raw_summary = snapshot.get("summary_lines", [])
        if not isinstance(raw_messages, list) or not isinstance(raw_summary, list):
            raise ValueError("checkpoint 上下文格式不正确")
        self._messages = [self._message_from_dict(item) for item in raw_messages]
        self._summary_lines = [str(item) for item in raw_summary]
        if len(self._messages) < 2:
            raise ValueError("checkpoint 缺少系统消息或用户任务")

    def _compact_if_needed(self) -> None:
        groups = self._completed_groups()
        while (
            self._messages_size(self._messages_with_summary())
            > self.max_context_chars
            and len(groups) > self.recent_groups
        ):
            group = groups.pop(0)
            self._summary_lines.append(self._summarize_group(group))
            self._trim_summary()
            del self._messages[2 : 2 + len(group)]

    def _completed_groups(self) -> list[list[Message]]:
        """按 assistant 及其紧随的 tool results 划分完整回合。"""

        groups: list[list[Message]] = []
        current: list[Message] = []
        for message in self._messages[2:]:
            if message.role == "assistant":
                if current:
                    groups.append(current)
                current = [message]
            elif current:
                current.append(message)
        if current:
            groups.append(current)
        return groups

    def _messages_with_summary(self) -> list[Message]:
        messages = list(self._messages)
        if self._summary_lines:
            messages.insert(
                2,
                Message(role="system", content="\n".join(self._summary_lines)),
            )
        return messages

    def _summarize_group(self, group: list[Message]) -> str:
        assistant = group[0]
        parts: list[str] = []
        if assistant.content:
            parts.append(f"assistant={self._clip(assistant.content, 240)}")
        for call in assistant.tool_calls:
            parts.append(self._summarize_call(call))
        for result in group[1:]:
            parts.append(
                f"result[{result.tool_call_id}]="
                f"{self._clip(result.content or '', 400)}"
            )
        return " | ".join(parts) or "completed empty assistant turn"

    def _summarize_call(self, call: ToolCall) -> str:
        arguments: dict[str, object] = {}
        for key in ("path", "query", "max_depth", "timeout"):
            if key in call.arguments:
                arguments[key] = call.arguments[key]
        command = call.arguments.get("command")
        if command is not None:
            arguments["command"] = command
        if call.name == "apply_patch":
            arguments["old_text_chars"] = len(call.arguments.get("old_text", ""))
            arguments["new_text_chars"] = len(call.arguments.get("new_text", ""))
        encoded = json.dumps(arguments, ensure_ascii=False, default=repr)
        return f"tool={call.name}({self._clip(encoded, 300)})"

    def _trim_summary(self) -> None:
        while (
            len("\n".join(self._summary_lines)) > self.max_summary_chars
            and len(self._summary_lines) > 1
        ):
            self._summary_lines.pop(0)
        if self._summary_lines:
            self._summary_lines[0] = self._clip(
                self._summary_lines[0], self.max_summary_chars
            )

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + f"…[省略 {len(text) - limit} 字符]"

    @staticmethod
    def _messages_size(messages: list[Message]) -> int:
        total = 0
        for message in messages:
            total += len(message.role) + len(message.content or "")
            total += len(message.tool_call_id or "")
            for call in message.tool_calls:
                total += len(call.id) + len(call.name)
                total += len(
                    json.dumps(call.arguments, ensure_ascii=False, default=repr)
                )
        return total

    @staticmethod
    def _message_to_dict(message: Message) -> dict[str, object]:
        return {
            "role": message.role,
            "content": message.content,
            "tool_call_id": message.tool_call_id,
            "tool_calls": [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in message.tool_calls
            ],
        }

    @staticmethod
    def _message_from_dict(value: object) -> Message:
        if not isinstance(value, dict):
            raise ValueError("checkpoint 消息格式不正确")
        role = value.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            raise ValueError("checkpoint 消息角色不正确")
        raw_calls = value.get("tool_calls", [])
        if not isinstance(raw_calls, list):
            raise ValueError("checkpoint 工具调用格式不正确")
        calls = [
            ToolCall(
                id=str(call["id"]),
                name=str(call["name"]),
                arguments=dict(call["arguments"]),
            )
            for call in raw_calls
            if isinstance(call, dict)
        ]
        return Message(
            role=role,
            content=value.get("content"),
            tool_calls=calls,
            tool_call_id=value.get("tool_call_id"),
        )
