"""验证审批策略和 ToolRegistry 拒绝路径。"""

from patchpilot.approvals import InteractiveApproval
from patchpilot.schemas import ToolCall


def test_read_tools_are_automatically_approved() -> None:
    prompts = []
    approval = InteractiveApproval(lambda text: prompts.append(text) or False)
    assert approval(ToolCall("1", "read_file", {"path": "a.py"}))
    assert prompts == []


def test_patch_requires_confirmation() -> None:
    prompts = []
    approval = InteractiveApproval(lambda text: prompts.append(text) or False)
    assert not approval(ToolCall("1", "apply_patch", {"path": "a.py"}))
    assert "a.py" in prompts[0]


def test_pytest_is_automatically_approved() -> None:
    approval = InteractiveApproval(lambda _: False)
    assert approval(ToolCall("1", "run_command", {"command": ["python", "-m", "pytest", "-q"]}))


def test_python_code_requires_confirmation() -> None:
    approval = InteractiveApproval(lambda _: False)
    assert not approval(ToolCall("1", "run_command", {"command": ["python", "-c", "print(1)"]}))


def test_invalid_command_shape_is_left_to_tool_validation() -> None:
    prompts = []
    approval = InteractiveApproval(lambda text: prompts.append(text) or False)
    assert approval(ToolCall("1", "run_command", {"command": '["python"]'}))
    assert prompts == []


def test_auto_approve_skips_confirmation() -> None:
    approval = InteractiveApproval(lambda _: False, auto_approve=True)
    assert approval(ToolCall("1", "apply_patch", {"path": "a.py"}))
