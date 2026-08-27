"""
文件名：test_events.py

功能：
验证终端工具输出不会把源码方括号当作 Rich 标记。
"""

from io import StringIO

from rich.console import Console

from patchpilot.events import RichEventSink
from patchpilot.schemas import ToolCall, ToolResult


def test_tool_output_preserves_square_brackets() -> None:
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    sink = RichEventSink(console)
    call = ToolCall("1", "read_file", {"path": "pyproject.toml"})
    result = ToolResult(
        "1", "read_file", True,
        "[project]\nself._tools[tool.name] = tool",
    )
    sink.tool_finished(call, result)
    output = stream.getvalue()
    assert "[project]" in output
    assert "[tool.name]" in output
