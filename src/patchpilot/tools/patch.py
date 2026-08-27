"""
文件名：tools/patch.py

功能：
实现安全的文件内容替换工具。

设计说明：
第一版不解析复杂的 unified diff，而是使用精确文本替换。
只有当 old_text 在目标文件中恰好出现一次时才执行修改，
从而降低模型误改代码位置的风险。
"""

import difflib
import os
import tempfile
from pathlib import Path
from typing import Any

from patchpilot.tools.base import Tool, ToolError
from patchpilot.workspace import Workspace


class ApplyPatchTool(Tool):
    """通过精确文本匹配修改工作区内的 UTF-8 文件。"""

    name = "apply_patch"
    description = (
        "修改工作区内的文本文件。old_text 必须在文件中恰好出现一次，"
        "修改成功后返回 unified diff。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "相对工作区的文件路径",
            },
            "old_text": {
                "type": "string",
                "description": "需要被替换的原始文本",
            },
            "new_text": {
                "type": "string",
                "description": "替换后的新文本",
            },
        },
        "required": ["path", "old_text", "new_text"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        workspace: Workspace,
        max_file_chars: int = 1_000_000,
    ) -> None:
        self.workspace = workspace
        self.max_file_chars = max_file_chars

    def execute(self, arguments: dict[str, Any]) -> str:
        """校验参数、执行原子替换并返回差异。"""

        path = self._require_string(arguments, "path")
        old_text = self._require_string(arguments, "old_text")
        new_text = self._require_string(
            arguments,
            "new_text",
            allow_empty=True,
        )

        if not old_text:
            raise ToolError("old_text 不能为空")

        target = self.workspace.resolve(path)
        self._validate_target(target, path)

        original = self._read_text(target, path)

        if len(original) > self.max_file_chars:
            raise ToolError(
                f"文件过大，最多允许修改 {self.max_file_chars} 个字符"
            )

        occurrence_count = original.count(old_text)

        if occurrence_count == 0:
            raise ToolError(
                "未找到 old_text，文件可能已经发生变化；"
                "请重新读取文件后再生成补丁"
            )

        if occurrence_count > 1:
            raise ToolError(
                f"old_text 在文件中出现了 {occurrence_count} 次，"
                "请提供包含更多上下文的唯一文本"
            )

        updated = original.replace(old_text, new_text, 1)

        if updated == original:
            raise ToolError("替换前后内容没有变化")

        # 先生成 diff。只有能够明确展示改动时才写入文件。
        diff = self._make_diff(path, original, updated)

        # 使用同目录临时文件和 os.replace() 实现原子替换，
        # 避免程序中途退出时留下半个文件。
        self._atomic_write(target, updated)

        return f"已修改：{path}\n\n{diff}"

    def _require_string(
        self,
        arguments: dict[str, Any],
        name: str,
        allow_empty: bool = False,
    ) -> str:
        """读取并校验字符串参数。"""

        value = arguments.get(name)

        if not isinstance(value, str):
            raise ToolError(f"参数 {name} 必须是字符串")

        if not allow_empty and not value.strip():
            raise ToolError(f"参数 {name} 不能为空")

        return value

    def _validate_target(self, target: Path, display_path: str) -> None:
        """确认目标是一个已存在的普通文件。"""

        if not target.exists():
            raise ToolError(f"文件不存在：{display_path}")

        if not target.is_file():
            raise ToolError(f"路径不是文件：{display_path}")

    def _read_text(self, target: Path, display_path: str) -> str:
        """读取 UTF-8 文本，并保留原始换行风格。"""

        try:
            with target.open(
                "r",
                encoding="utf-8",
                newline="",
            ) as stream:
                return stream.read()
        except UnicodeDecodeError as error:
            raise ToolError(
                f"文件不是有效的 UTF-8 文本：{display_path}"
            ) from error
        except PermissionError as error:
            raise ToolError(
                f"没有权限读取文件：{display_path}"
            ) from error

    def _atomic_write(self, target: Path, content: str) -> None:
        """通过临时文件原子更新目标文件。"""

        temporary_path: str | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = stream.name
                stream.write(content)
                stream.flush()

                # 确保操作系统已经接收到写入内容
                os.fsync(stream.fileno())

            # 保留目标文件原来的权限位，例如可执行权限
            os.chmod(temporary_path, target.stat().st_mode)

            # 同一文件系统中的 os.replace() 是原子操作
            os.replace(temporary_path, target)

        except PermissionError as error:
            raise ToolError(f"没有权限修改文件：{target}") from error
        except OSError as error:
            raise ToolError(f"写入文件失败：{error}") from error
        finally:
            # 如果替换前发生异常，清理遗留的临时文件
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def _make_diff(
        self,
        path: str,
        original: str,
        updated: str,
    ) -> str:
        """生成便于用户和模型阅读的 unified diff。"""

        lines = difflib.unified_diff(
            original.splitlines(),
            updated.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )

        return "\n".join(lines)