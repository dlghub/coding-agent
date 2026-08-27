"""
文件名：approvals.py

功能：
定义工具审批策略。只读操作和明确的验证命令自动允许，文件修改与
其他命令默认请求用户确认；被工具硬禁止的命令仍无法通过审批绕过。
"""

from collections.abc import Callable
from pathlib import Path

from patchpilot.schemas import ToolCall


PromptFunction = Callable[[str], bool]


class InteractiveApproval:
    """根据工具风险决定自动允许或请求确认。"""

    def __init__(self, prompt: PromptFunction, auto_approve: bool = False) -> None:
        self.prompt = prompt
        self.auto_approve = auto_approve

    def __call__(self, call: ToolCall) -> bool:
        """返回工具调用是否获准执行。"""

        if call.name in {"list_files", "read_file", "search_text"}:
            return True
        if self.auto_approve:
            return True
        if call.name == "apply_patch":
            path = call.arguments.get("path", "[未知文件]")
            return self.prompt(f"允许 Agent 修改文件 {path} 吗？")
        if call.name == "run_command":
            command = call.arguments.get("command")
            # 参数格式错误时先让工具自己的校验返回明确错误，避免询问用户。
            if not isinstance(command, list):
                return True
            if self._is_safe_verification_command(command):
                return True
            return self.prompt(f"允许 Agent 执行命令 {command!r} 吗？")
        return self.prompt(f"允许 Agent 调用工具 {call.name} 吗？")

    def _is_safe_verification_command(self, command: object) -> bool:
        """识别不会主动修改源码的常见检查命令。"""

        if not isinstance(command, list) or not command:
            return False
        if any(not isinstance(item, str) for item in command):
            return False

        program = Path(command[0]).name.lower()
        if program in {"pytest", "ruff", "mypy"}:
            return True
        if program in {"python", "python3"} and len(command) >= 3:
            return command[1:3] in (["-m", "pytest"], ["-m", "ruff"], ["-m", "mypy"])
        if program == "git" and len(command) >= 2:
            return command[1].lower() in {"status", "diff", "log", "show"}
        return False
