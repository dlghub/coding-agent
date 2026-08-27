"""
文件名：tools/shell.py

功能：
在受约束的项目工作区内执行本地命令。

安全说明：
本工具不启用 shell，也不接受完整 shell 字符串。
这可以避免管道、重定向、命令替换等常见注入方式。

注意：
命令黑名单并不等同于真正的操作系统沙箱。
后续仍应为高风险命令增加用户审批机制。
"""

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from patchpilot.tools.base import Tool, ToolError
from patchpilot.workspace import Workspace


# 第一版直接拒绝这些具有明显系统破坏性或提权能力的程序
BLOCKED_PROGRAMS = {
    "apt",
    "apt-get",
    "bash",
    "cmd",
    "doas",
    "dnf",
    "fish",
    "halt",
    "kill",
    "killall",
    "mkfs",
    "mount",
    "npm",
    "pacman",
    "pip",
    "pip3",
    "pnpm",
    "poweroff",
    "powershell",
    "pwsh",
    "reboot",
    "rm",
    "sh",
    "shutdown",
    "sudo",
    "su",
    "yum",
    "zsh",
}

# Git 本身可以用于查看差异和状态，但这些子命令风险较高
BLOCKED_GIT_SUBCOMMANDS = {
    "clean",
    "push",
    "reset",
    "restore",
}


class RunCommandTool(Tool):
    """在工作区中执行无 shell 的子进程命令。"""

    name = "run_command"
    description = (
        "在工作区内运行测试、格式检查或其他开发命令。"
        "command 必须是字符串数组，不支持管道和重定向。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": (
                    '命令及参数数组，例如 ["python", "-m", "pytest", "-q"]'
                ),
            },
            "timeout": {
                "type": "integer",
                "minimum": 1,
                "maximum": 300,
                "description": "命令超时时间，单位为秒",
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        workspace: Workspace,
        default_timeout: int = 60,
        max_timeout: int = 300,
        max_output_chars: int = 20_000,
    ) -> None:
        self.workspace = workspace
        self.default_timeout = default_timeout
        self.max_timeout = max_timeout
        self.max_output_chars = max_output_chars

    def execute(self, arguments: dict[str, Any]) -> str:
        """校验并执行命令，返回退出码和输出。"""

        command = self._validate_command(arguments.get("command"))
        timeout = self._validate_timeout(arguments.get("timeout"))

        self._check_command_policy(command)

        try:
            completed = subprocess.run(
                command,

                # 始终固定在工作区运行
                cwd=self.workspace.root,

                # 捕获输出，交给模型判断命令结果
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",

                # 不启用 shell，防止解析 |、>、$() 等语法
                shell=False,
                timeout=timeout,
                check=False,

                # 不向测试程序泄露模型 API Key
                env=self._safe_environment(),
            )
        except subprocess.TimeoutExpired as error:
            stdout = self._normalise_timeout_output(error.stdout)
            stderr = self._normalise_timeout_output(error.stderr)

            return self._format_result(
                command=command,
                exit_code=None,
                stdout=stdout,
                stderr=stderr,
                timed_out=True,
                timeout=timeout,
            )
        except FileNotFoundError as error:
            raise ToolError(f"找不到可执行程序：{command[0]}") from error
        except PermissionError as error:
            raise ToolError(f"没有权限执行程序：{command[0]}") from error
        except OSError as error:
            raise ToolError(f"命令启动失败：{error}") from error

        return self._format_result(
            command=command,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
            timeout=timeout,
        )

    def _validate_command(self, value: Any) -> list[str]:
        """确认 command 是非空字符串数组。"""

        if not isinstance(value, list) or not value:
            raise ToolError("参数 command 必须是非空字符串数组")

        if any(not isinstance(item, str) for item in value):
            raise ToolError("command 中的每一项都必须是字符串")

        if any(not item for item in value):
            raise ToolError("command 中不能包含空字符串")

        if any("\x00" in item for item in value):
            raise ToolError("command 中不能包含空字符")

        if sum(len(item) for item in value) > 20_000:
            raise ToolError("命令参数过长")

        return value

    def _validate_timeout(self, value: Any) -> int:
        """校验命令超时时间。"""

        if value is None:
            return self.default_timeout

        # bool 是 int 的子类，因此需要单独拒绝
        if isinstance(value, bool) or not isinstance(value, int):
            raise ToolError("参数 timeout 必须是整数")

        if not 1 <= value <= self.max_timeout:
            raise ToolError(
                f"timeout 必须在 1 到 {self.max_timeout} 秒之间"
            )

        return value

    def _check_command_policy(self, command: list[str]) -> None:
        """拒绝第一版中不允许自动执行的高风险命令。"""

        program = Path(command[0]).name.lower()

        if program in BLOCKED_PROGRAMS:
            raise ToolError(f"出于安全考虑，禁止执行命令：{program}")

        if program == "git" and len(command) >= 2:
            subcommand = command[1].lower()

            if subcommand in BLOCKED_GIT_SUBCOMMANDS:
                raise ToolError(
                    f"出于安全考虑，禁止自动执行：git {subcommand}"
                )

    def _safe_environment(self) -> dict[str, str]:
        """创建子进程环境，并移除模型服务凭据。"""

        environment = os.environ.copy()

        sensitive_names = {
            "AGENT_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
        }

        for name in sensitive_names:
            environment.pop(name, None)

        return environment

    def _normalise_timeout_output(
        self,
        output: str | bytes | None,
    ) -> str:
        """兼容不同 Python 版本中的 TimeoutExpired 输出类型。"""

        if output is None:
            return ""

        if isinstance(output, bytes):
            return output.decode("utf-8", errors="replace")

        return output

    def _format_result(
        self,
        command: list[str],
        exit_code: int | None,
        stdout: str,
        stderr: str,
        timed_out: bool,
        timeout: int,
    ) -> str:
        """生成统一且长度受限的命令结果。"""

        display_command = shlex.join(command)

        if timed_out:
            status = f"状态：超时（超过 {timeout} 秒）"
        else:
            status = f"退出码：{exit_code}"

        result = (
            f"命令：{display_command}\n"
            f"{status}\n\n"
            f"stdout:\n{stdout.rstrip() or '[无输出]'}\n\n"
            f"stderr:\n{stderr.rstrip() or '[无输出]'}"
        )

        if len(result) <= self.max_output_chars:
            return result

        removed = len(result) - self.max_output_chars

        return (
            result[: self.max_output_chars]
            + f"\n\n[命令输出已截断，省略 {removed} 个字符]"
        )