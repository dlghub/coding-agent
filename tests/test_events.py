"""
文件名：test_events.py

功能：
验证终端工具输出不会把源码方括号当作 Rich 标记。
"""

from io import StringIO

from rich.console import Console

from patchpilot.events import RichEventSink
from patchpilot.git_review import GitReview
from patchpilot.outcome import RunSummary, VerificationEvidence
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


def test_run_summary_renders_evidence() -> None:
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    sink = RichEventSink(console)
    summary = RunSummary(
        status="partial",
        changed_files=["app.py"],
        verifications=[
            VerificationEvidence(["python", "-m", "pytest", "-q"], False, 2)
        ],
        verification_current=False,
        warnings=["最后一次修改之后没有成功的验证记录。"],
        git_review=GitReview(
            available=True,
            status_lines=[" M app.py", "?? new.py"],
            diff_stat="app.py | 2 +−",
            diff_check_passed=False,
        ),
    )

    sink.run_summary(summary)

    output = stream.getvalue()
    assert "可信状态：部分完成" in output
    assert "app.py" in output
    assert "python -m pytest -q" in output
    assert "警告" in output
    assert "?? new.py" in output
    assert "git diff --check" in output
