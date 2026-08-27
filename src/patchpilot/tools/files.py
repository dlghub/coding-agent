"""
文件名：tools/files.py

功能：
实现目录浏览和带行号的文本读取工具。
"""

from pathlib import Path
from typing import Any

from patchpilot.tools.base import Tool, ToolError
from patchpilot.workspace import Workspace


IGNORED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "patchpilot.egg-info",
}


def _integer_argument(
    arguments: dict[str, Any],
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    """读取并校验整数参数，避免 bool 被当作整数接受。"""

    value = arguments.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"参数 {name} 必须是整数")
    if not minimum <= value <= maximum:
        raise ToolError(f"参数 {name} 必须在 {minimum} 到 {maximum} 之间")
    return value


class ListFilesTool(Tool):
    """按稳定顺序列出工作区中的目录树。"""

    name = "list_files"
    description = "列出工作区内的文件和目录，不读取文件内容。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对工作区的目录路径"},
            "max_depth": {
                "type": "integer",
                "minimum": 0,
                "maximum": 8,
                "description": "递归深度",
            },
        },
        "required": [],
        "additionalProperties": False,
    }

    def __init__(self, workspace: Workspace, max_entries: int = 500) -> None:
        self.workspace = workspace
        self.max_entries = max_entries

    def execute(self, arguments: dict[str, Any]) -> str:
        path = arguments.get("path", ".")
        if not isinstance(path, str):
            raise ToolError("参数 path 必须是字符串")

        # 模型常用空字符串表示当前工作区
        path = path.strip() or "."

        max_depth = _integer_argument(arguments, "max_depth", 3, 0, 8)
        root = self.workspace.resolve(path)
        if not root.exists():
            raise ToolError(f"目录不存在：{path}")
        if not root.is_dir():
            raise ToolError(f"路径不是目录：{path}")

        lines: list[str] = []
        truncated = self._walk(root, root, max_depth, lines)
        if not lines:
            return f"目录 {path} 为空"
        if truncated:
            lines.append(f"[结果已截断，最多显示 {self.max_entries} 项]")
        return "\n".join(lines)

    def _walk(
        self,
        root: Path,
        current: Path,
        max_depth: int,
        lines: list[str],
    ) -> bool:
        if len(lines) >= self.max_entries:
            return True

        depth = len(current.relative_to(root).parts)
        if depth > max_depth:
            return False

        try:
            children = sorted(current.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        except PermissionError as error:
            raise ToolError(f"没有权限读取目录：{current}") from error

        for child in children:
            if self.workspace.is_sensitive(child):
                continue

            if child.is_dir() and (child.name in IGNORED_DIRECTORIES or child.name.endswith(".egg-info")):
                continue
            if len(lines) >= self.max_entries:
                return True

            child_depth = len(child.relative_to(root).parts)
            if child_depth > max_depth:
                continue

            suffix = "/" if child.is_dir() else ""
            lines.append(f"{'  ' * (child_depth - 1)}{child.name}{suffix}")
            if child.is_dir() and self._walk(root, child, max_depth, lines):
                return True

        return False


class ReadFileTool(Tool):
    """读取 UTF-8 文本文件的指定行范围。"""

    name = "read_file"
    description = "读取工作区内文本文件的指定行，并返回行号。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对工作区的文件路径"},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(self, workspace: Workspace, max_lines: int = 400) -> None:
        self.workspace = workspace
        self.max_lines = max_lines

    def execute(self, arguments: dict[str, Any]) -> str:
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ToolError("参数 path 必须是非空字符串")

        start = _integer_argument(arguments, "start_line", 1, 1, 10_000_000)
        end = _integer_argument(arguments, "end_line", start + 199, 1, 10_000_000)
        if end < start:
            raise ToolError("end_line 不能小于 start_line")
        if end - start + 1 > self.max_lines:
            raise ToolError(f"单次最多读取 {self.max_lines} 行")

        target = self.workspace.resolve(path)
        if not target.exists():
            raise ToolError(f"文件不存在：{path}")
        if not target.is_file():
            raise ToolError(f"路径不是文件：{path}")

        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as error:
            raise ToolError(f"文件不是有效的 UTF-8 文本：{path}") from error
        except PermissionError as error:
            raise ToolError(f"没有权限读取文件：{path}") from error

        selected = lines[start - 1 : end]
        if not selected:
            return f"文件：{path}\n请求范围没有内容（文件共 {len(lines)} 行）"

        numbered = [f"{number} | {line}" for number, line in enumerate(selected, start=start)]
        actual_end = start + len(selected) - 1
        return f"文件：{path}\n行号：{start}-{actual_end}\n\n" + "\n".join(numbered)
