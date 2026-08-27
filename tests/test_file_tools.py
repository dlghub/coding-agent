"""
文件名：test_file_tools.py

功能：
验证目录浏览、文本读取和 ripgrep 搜索工具。
"""

import shutil
from pathlib import Path

import pytest

from patchpilot.tools.base import ToolError
from patchpilot.tools.files import ListFilesTool, ReadFileTool
from patchpilot.tools.search import SearchTextTool
from patchpilot.workspace import Workspace, WorkspaceViolation


def test_list_files_is_sorted_and_ignores_generated_directories(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "b.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "a.py").write_text("", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("secret", encoding="utf-8")

    output = ListFilesTool(Workspace(tmp_path)).execute({"max_depth": 2})

    assert output.splitlines() == ["src/", "  a.py", "  b.py"]
    assert ".git" not in output


def test_list_files_respects_max_depth(tmp_path: Path) -> None:
    nested = tmp_path / "one" / "two"
    nested.mkdir(parents=True)
    (nested / "deep.txt").write_text("data", encoding="utf-8")

    output = ListFilesTool(Workspace(tmp_path)).execute({"max_depth": 1})

    assert "one/" in output
    assert "two" not in output


def test_read_file_returns_numbered_range(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("first\nsecond\nthird\n", encoding="utf-8")

    output = ReadFileTool(Workspace(tmp_path)).execute(
        {"path": "app.py", "start_line": 2, "end_line": 3}
    )

    assert "行号：2-3" in output
    assert "2 | second" in output
    assert "3 | third" in output
    assert "first" not in output


def test_read_file_rejects_directory(tmp_path: Path) -> None:
    with pytest.raises(ToolError, match="不是文件"):
        ReadFileTool(Workspace(tmp_path)).execute({"path": "."})


def test_read_file_rejects_too_many_lines(tmp_path: Path) -> None:
    (tmp_path / "large.txt").write_text("line\n" * 10, encoding="utf-8")
    with pytest.raises(ToolError, match="最多读取"):
        ReadFileTool(Workspace(tmp_path), max_lines=2).execute(
            {"path": "large.txt", "start_line": 1, "end_line": 3}
        )


def test_read_file_rejects_workspace_escape(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceViolation):
        ReadFileTool(Workspace(tmp_path)).execute({"path": "../secret.txt"})


@pytest.mark.skipif(shutil.which("rg") is None, reason="系统未安装 ripgrep")
def test_search_text_finds_matching_python_file(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def calculate_total():\n    pass\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("calculate_total\n", encoding="utf-8")

    output = SearchTextTool(Workspace(tmp_path)).execute(
        {"query": "calculate_total", "glob": "*.py"}
    )

    assert "app.py:1:" in output
    assert "notes.txt" not in output


@pytest.mark.skipif(shutil.which("rg") is None, reason="系统未安装 ripgrep")
def test_search_text_reports_no_match(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    output = SearchTextTool(Workspace(tmp_path)).execute({"query": "missing"})
    assert output == "未找到匹配内容"
