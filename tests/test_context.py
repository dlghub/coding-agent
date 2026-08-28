"""验证 Agent 上下文保存、工具消息配对和历史压缩。"""

import pytest

from patchpilot.context import ContextManager
from patchpilot.schemas import ModelResponse, ToolCall, ToolResult


def add_tool_turn(context: ContextManager, index: int, output: str) -> None:
    call = ToolCall(
        f"call-{index}", "read_file", {"path": f"file_{index}.py"}
    )
    context.add_assistant_response(ModelResponse(tool_calls=[call]))
    context.add_tool_result(ToolResult(call.id, call.name, True, output))


def test_context_keeps_messages_when_under_budget() -> None:
    context = ContextManager("system", max_context_chars=2_000)
    context.start("task")
    add_tool_turn(context, 1, "small result")

    messages = context.messages()

    assert [message.role for message in messages] == [
        "system", "user", "assistant", "tool"
    ]
    assert messages[-1].tool_call_id == "call-1"


def test_context_compacts_old_groups_and_preserves_recent_pairs() -> None:
    context = ContextManager(
        "system prompt",
        max_context_chars=1_200,
        recent_groups=1,
        max_summary_chars=400,
    )
    context.start("original task")
    for index in range(1, 5):
        add_tool_turn(context, index, f"result-{index}-" + "x" * 700)

    messages = context.messages()

    assert messages[0].content == "system prompt"
    assert messages[1].content == "original task"
    assert messages[2].role == "system"
    assert "Earlier execution summary" in (messages[2].content or "")
    assert [message.role for message in messages[-2:]] == ["assistant", "tool"]
    assert messages[-1].tool_call_id == messages[-2].tool_calls[0].id
    assert "result-4" in (messages[-1].content or "")
    assert context.estimated_chars() < 2_000


def test_context_summary_does_not_store_patch_body() -> None:
    context = ContextManager(
        "system", max_context_chars=1_000, recent_groups=1, max_summary_chars=300
    )
    context.start("task")
    secret_body = "UNIQUE_PATCH_BODY" * 100
    call = ToolCall(
        "patch-1",
        "apply_patch",
        {"path": "a.py", "old_text": "old", "new_text": secret_body},
    )
    context.add_assistant_response(ModelResponse(tool_calls=[call]))
    context.add_tool_result(ToolResult("patch-1", "apply_patch", True, "ok"))
    add_tool_turn(context, 2, "y" * 1_000)

    combined = "\n".join(message.content or "" for message in context.messages())

    assert secret_body not in combined
    assert "new_text_chars" in combined


def test_start_clears_previous_summary() -> None:
    context = ContextManager("system", max_context_chars=1_000, recent_groups=1)
    context.start("first")
    for index in range(3):
        add_tool_turn(context, index, "x" * 800)
    assert any(
        "Earlier execution summary" in (item.content or "")
        for item in context.messages()
    )

    context.start("second")

    assert [message.content for message in context.messages()] == [
        "system", "second"
    ]


def test_context_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError, match="至少为 1000"):
        ContextManager("system", max_context_chars=999)


def test_context_snapshot_round_trip_preserves_tool_pair() -> None:
    original = ContextManager("system")
    original.start("task")
    add_tool_turn(original, 1, "result")

    restored = ContextManager("different system")
    restored.restore(original.snapshot())

    messages = restored.messages()
    assert [message.role for message in messages] == [
        "system", "user", "assistant", "tool"
    ]
    assert messages[-2].tool_calls[0].id == "call-1"
    assert messages[-1].tool_call_id == "call-1"


def test_context_adds_user_message_without_resetting_history() -> None:
    context = ContextManager("system")
    context.start("first task")
    context.add_assistant_response(ModelResponse(content="first answer"))

    context.add_user_message("follow up")

    assert [message.content for message in context.messages()] == [
        "system", "first task", "first answer", "follow up"
    ]


def test_context_clear_removes_messages_and_summary() -> None:
    context = ContextManager("system")
    context.start("task")
    context.add_assistant_response(ModelResponse(content="answer"))

    context.clear()

    assert context.messages() == []
