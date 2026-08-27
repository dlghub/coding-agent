"""
文件名：test_patch_tool.py

功能：
验证精确文本补丁工具的正确性和安全边界。
"""

from pathlib import Path

import pytest

from patchpilot.tools.base import ToolError
from patchpilot.tools.patch import ApplyPatchTool
from patchpilot.workspace import Workspace, WorkspaceViolation


def test_apply_patch_replaces_unique_text(tmp_path: Path) -> None:
    target = tmp_path / "cart.py"
    target.write_text(
        "def total(price, discount):\n"
        "    return price * discount\n",
        encoding="utf-8",
    )

    tool = ApplyPatchTool(Workspace(tmp_path))

    output = tool.execute(
        {
            "path": "cart.py",
            "old_text": "return price * discount",
            "new_text": "return price * (1 - discount)",
        }
    )

    assert "return price * (1 - discount)" in target.read_text(
        encoding="utf-8"
    )
    assert "--- a/cart.py" in output
    assert "+++ b/cart.py" in output
    assert "-    return price * discount" in output
    assert "+    return price * (1 - discount)" in output


def test_apply_patch_creates_new_file_with_empty_old_text(
    tmp_path: Path,
) -> None:
    target = tmp_path / "new_module.py"
    tool = ApplyPatchTool(Workspace(tmp_path))

    output = tool.execute(
        {
            "path": "new_module.py",
            "old_text": "",
            "new_text": "VALUE = 42\n",
        }
    )

    assert target.read_text(encoding="utf-8") == "VALUE = 42\n"
    assert "+++ b/new_module.py" in output


def test_apply_patch_writes_empty_existing_file_with_empty_old_text(
    tmp_path: Path,
) -> None:
    target = tmp_path / "empty.py"
    target.touch()
    tool = ApplyPatchTool(Workspace(tmp_path))

    tool.execute(
        {
            "path": "empty.py",
            "old_text": "",
            "new_text": "print('ready')\n",
        }
    )

    assert target.read_text(encoding="utf-8") == "print('ready')\n"


def test_apply_patch_rejects_empty_old_text_for_nonempty_file(
    tmp_path: Path,
) -> None:
    target = tmp_path / "existing.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    tool = ApplyPatchTool(Workspace(tmp_path))

    with pytest.raises(ToolError, match="空 old_text"):
        tool.execute(
            {
                "path": "existing.py",
                "old_text": "",
                "new_text": "VALUE = 2\n",
            }
        )

    assert target.read_text(encoding="utf-8") == "VALUE = 1\n"


def test_apply_patch_rejects_missing_old_text(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("print('hello')\n", encoding="utf-8")

    tool = ApplyPatchTool(Workspace(tmp_path))

    with pytest.raises(ToolError, match="未找到 old_text"):
        tool.execute(
            {
                "path": "app.py",
                "old_text": "print('missing')",
                "new_text": "print('new')",
            }
        )

    # 修改失败时，原文件必须保持不变
    assert target.read_text(encoding="utf-8") == "print('hello')\n"


def test_apply_patch_rejects_multiple_matches(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text(
        "value = 1\nvalue = 1\n",
        encoding="utf-8",
    )

    tool = ApplyPatchTool(Workspace(tmp_path))

    with pytest.raises(ToolError, match="出现了 2 次"):
        tool.execute(
            {
                "path": "app.py",
                "old_text": "value = 1",
                "new_text": "value = 2",
            }
        )


def test_apply_patch_can_delete_text(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text(
        "first\nremove me\nlast\n",
        encoding="utf-8",
    )

    tool = ApplyPatchTool(Workspace(tmp_path))

    tool.execute(
        {
            "path": "app.py",
            "old_text": "remove me\n",
            "new_text": "",
        }
    )

    assert target.read_text(encoding="utf-8") == "first\nlast\n"


def test_apply_patch_rejects_directory(tmp_path: Path) -> None:
    tool = ApplyPatchTool(Workspace(tmp_path))

    with pytest.raises(ToolError, match="不是文件"):
        tool.execute(
            {
                "path": ".",
                "old_text": "old",
                "new_text": "new",
            }
        )


def test_apply_patch_rejects_binary_file(tmp_path: Path) -> None:
    target = tmp_path / "binary.dat"
    target.write_bytes(b"\xff\xfe\x00\x01")

    tool = ApplyPatchTool(Workspace(tmp_path))

    with pytest.raises(ToolError, match="UTF-8"):
        tool.execute(
            {
                "path": "binary.dat",
                "old_text": "old",
                "new_text": "new",
            }
        )


def test_apply_patch_rejects_workspace_escape(tmp_path: Path) -> None:
    tool = ApplyPatchTool(Workspace(tmp_path))

    with pytest.raises(WorkspaceViolation):
        tool.execute(
            {
                "path": "../secret.txt",
                "old_text": "old",
                "new_text": "new",
            }
        )
