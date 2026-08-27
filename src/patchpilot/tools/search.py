"""
文件名：tools/search.py

功能：
使用 ripgrep 在工作区内快速搜索文本。
"""

import shutil
import subprocess
from typing import Any

from patchpilot.tools.base import Tool, ToolError
from patchpilot.workspace import Workspace


class SearchTextTool(Tool):
    """调用 rg 搜索文本，并限制执行时间与输出规模。"""

    name = "search_text"
    description = "在工作区文本文件中搜索字符串或正则表达式。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索字符串或正则表达式"},
            "path": {"type": "string", "description": "相对工作区的搜索路径"},
            "glob": {"type": "string", "description": "可选文件过滤，例如 *.py"},
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        workspace: Workspace,
        timeout: float = 10.0,
        max_lines: int = 200,
        max_chars: int = 20_000,
    ) -> None:
        self.workspace = workspace
        self.timeout = timeout
        self.max_lines = max_lines
        self.max_chars = max_chars

    def execute(self, arguments: dict[str, Any]) -> str:
        query = arguments.get("query")
        path = arguments.get("path", ".")
        glob = arguments.get("glob")

        if not isinstance(query, str) or not query:
            raise ToolError("参数 query 必须是非空字符串")
        if not isinstance(path, str):
            raise ToolError("参数 path 必须是字符串")
        if glob is not None and not isinstance(glob, str):
            raise ToolError("参数 glob 必须是字符串")
        if shutil.which("rg") is None:
            raise ToolError("系统未安装 ripgrep（rg）")

        target = self.workspace.resolve(path)
        if not target.exists():
            raise ToolError(f"搜索路径不存在：{path}")

        command = [
            "rg",
            "--line-number",
            "--column",
            "--color",
            "never",
            "--no-heading",
            "--smart-case",

            # 即使用户的 .gitignore 配置错误，也不搜索敏感文件
            "--glob",
            "!.env",
            "--glob",
            "!.env.*",
            "--glob",
            "!.git/**",
            "--glob",
            "!*.pem",
            "--glob",
            "!*.key",
            "--glob",
            "!*.p12",
            "--glob",
            "!*.pfx",
        ]
        if glob:
            command.extend(["--glob", glob])
        command.extend(["--", query, str(target)])

        try:
            completed = subprocess.run(
                command,
                cwd=self.workspace.root,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise ToolError(f"搜索超过 {self.timeout} 秒，已终止") from error

        if completed.returncode == 1:
            return "未找到匹配内容"
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "未知错误"
            raise ToolError(f"rg 搜索失败：{detail}")

        lines = completed.stdout.splitlines()
        truncated = len(lines) > self.max_lines
        output = "\n".join(lines[: self.max_lines])
        if len(output) > self.max_chars:
            output = output[: self.max_chars]
            truncated = True
        if truncated:
            output += "\n[搜索结果已截断]"
        return output
