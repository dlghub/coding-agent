"""验证 JSONL 会话日志结构、脱敏和文件权限。"""

import json
import stat

from patchpilot.events import JsonlEventSink
from patchpilot.schemas import ToolCall, ToolResult


def test_session_log_records_events_and_redacts_patch_text(tmp_path) -> None:
    sink = JsonlEventSink(tmp_path, False, directory=tmp_path / "logs")
    call = ToolCall(
        "1", "apply_patch",
        {"path": "a.py", "old_text": "secret old", "new_text": "secret new"},
    )
    sink.agent_started("fix test")
    sink.step_started(1, 5)
    sink.tool_started(call)
    sink.tool_finished(call, ToolResult("1", "apply_patch", True, "ok"))
    sink.agent_finished("done")

    records = [json.loads(line) for line in sink.path.read_text(encoding="utf-8").splitlines()]
    assert [record["event"] for record in records] == [
        "session_created", "agent_started", "step_started",
        "tool_started", "tool_finished", "agent_finished",
    ]
    started = records[3]
    assert "old_text" not in started["arguments"]
    assert started["arguments"]["old_text_chars"] == len("secret old")
    assert stat.S_IMODE(sink.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(sink.directory.stat().st_mode) == 0o700
