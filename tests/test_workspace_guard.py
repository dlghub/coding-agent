"""
文件名：test_workspace_guard.py

功能：
验证工作区路径边界，包括普通路径、路径穿越和符号链接逃逸。
"""

from pathlib import Path

import pytest

from patchpilot.workspace import Workspace, WorkspaceViolation


def test_resolve_normal_relative_path(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    assert workspace.resolve("src/app.py") == (tmp_path / "src/app.py").resolve()


def test_rejects_empty_path(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    with pytest.raises(WorkspaceViolation, match="不能为空"):
        workspace.resolve("")


def test_rejects_parent_directory_escape(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    with pytest.raises(WorkspaceViolation, match="外部路径"):
        workspace.resolve("../secret.txt")


def test_rejects_absolute_path(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    with pytest.raises(WorkspaceViolation, match="绝对路径"):
        workspace.resolve("/etc/passwd")


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    link = tmp_path / "outside-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
        workspace = Workspace(tmp_path)
        with pytest.raises(WorkspaceViolation, match="外部路径"):
            workspace.resolve("outside-link/file.txt")
    finally:
        link.unlink(missing_ok=True)
        outside.rmdir()


def test_rejects_missing_workspace(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="不存在"):
        Workspace(tmp_path / "missing")
