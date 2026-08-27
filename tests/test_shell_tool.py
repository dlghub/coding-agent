"""
文件名：test_shell_tool.py

功能：
验证命令执行工具的输出、工作目录、超时和安全策略。
"""

import sys
from pathlib import Path

import pytest

from patchpilot.tools.base import ToolError
from patchpilot.tools.shell import RunCommandTool
from patchpilot.workspace import Workspace


def test_run_command_returns_stdout_and_exit_code(
    tmp_path: Path,
) -> None:
    tool = RunCommandTool(Workspace(tmp_path))

    output = tool.execute(
        {
            "command": [
                sys.executable,
                "-c",
                "print('hello from agent')",
            ]
        }
    )

    assert "退出码：0" in output
    assert "hello from agent" in output


def test_run_command_accepts_json_encoded_string_array(
    tmp_path: Path,
) -> None:
    tool = RunCommandTool(Workspace(tmp_path))

    output = tool.execute(
        {
            "command": (
                f'["{sys.executable}", "-c", '
                '"print(\\"recovered\\")"]'
            )
        }
    )

    assert "退出码：0" in output
    assert "recovered" in output


def test_json_encoded_dangerous_command_remains_blocked(
    tmp_path: Path,
) -> None:
    tool = RunCommandTool(Workspace(tmp_path))

    with pytest.raises(ToolError, match="禁止"):
        tool.execute({"command": '["rm", "-rf", "target"]'})


def test_run_command_uses_workspace_as_current_directory(
    tmp_path: Path,
) -> None:
    tool = RunCommandTool(Workspace(tmp_path))

    output = tool.execute(
        {
            "command": [
                sys.executable,
                "-c",
                "import os; print(os.getcwd())",
            ]
        }
    )

    assert str(tmp_path.resolve()) in output


def test_run_command_returns_nonzero_exit_code(
    tmp_path: Path,
) -> None:
    tool = RunCommandTool(Workspace(tmp_path))

    output = tool.execute(
        {
            "command": [
                sys.executable,
                "-c",
                "import sys; print('failed'); sys.exit(3)",
            ]
        }
    )

    # 非零退出码是模型需要分析的结果，不应抛出工具异常
    assert "退出码：3" in output
    assert "failed" in output


def test_run_command_reports_timeout(tmp_path: Path) -> None:
    tool = RunCommandTool(Workspace(tmp_path))

    output = tool.execute(
        {
            "command": [
                sys.executable,
                "-c",
                "import time; time.sleep(5)",
            ],
            "timeout": 1,
        }
    )

    assert "状态：超时" in output


@pytest.mark.parametrize(
    "command",
    [
        ["rm", "-rf", "target"],
        ["sudo", "echo", "hello"],
        ["bash", "-c", "echo hello"],
        ["git", "push"],
        ["git", "reset", "--hard"],
    ],
)
def test_run_command_rejects_dangerous_commands(
    tmp_path: Path,
    command: list[str],
) -> None:
    tool = RunCommandTool(Workspace(tmp_path))

    with pytest.raises(ToolError, match="禁止"):
        tool.execute({"command": command})


@pytest.mark.parametrize(
    "command",
    [
        "python -m pytest",
        [],
        [1, 2, 3],
        ["python", ""],
    ],
)
def test_run_command_requires_nonempty_string_array(
    tmp_path: Path,
    command: object,
) -> None:
    tool = RunCommandTool(Workspace(tmp_path))

    with pytest.raises(ToolError, match="command"):
        tool.execute({"command": command})


def test_run_command_does_not_expose_agent_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_API_KEY", "should-not-be-visible")
    tool = RunCommandTool(Workspace(tmp_path))

    output = tool.execute(
        {
            "command": [
                sys.executable,
                "-c",
                (
                    "import os; "
                    "print(os.environ.get('AGENT_API_KEY', 'missing'))"
                ),
            ]
        }
    )

    assert "should-not-be-visible" not in output
    assert "missing" in output
