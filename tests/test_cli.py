"""
文件名：test_cli.py

功能：
验证 CLI 只读模式在能力层面排除写入与命令执行工具。
"""

from pathlib import Path

from patchpilot.cli import build_tools
from patchpilot.workspace import Workspace


def test_read_only_mode_registers_only_inspection_tools(tmp_path: Path) -> None:
    names = {tool.name for tool in build_tools(Workspace(tmp_path), read_only=True)}
    assert names == {"list_files", "read_file", "search_text"}


def test_normal_mode_registers_all_tools(tmp_path: Path) -> None:
    names = {tool.name for tool in build_tools(Workspace(tmp_path), read_only=False)}
    assert names == {
        "list_files",
        "read_file",
        "search_text",
        "apply_patch",
        "run_command",
    }
