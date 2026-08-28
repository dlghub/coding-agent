"""离线验证持续对话输入、斜杠命令和审批切换。"""

from io import StringIO
from pathlib import Path

from rich.console import Console

from patchpilot.approvals import InteractiveApproval
from patchpilot.chat import ChatSession


class FakeAgent:
    def __init__(self) -> None:
        self.started = []
        self.continued = []
        self.reset_count = 0

    def run(self, task: str) -> str:
        self.started.append(task)
        return "ok"

    def continue_with(self, task: str) -> str:
        self.continued.append(task)
        return "ok"

    def reset_conversation(self) -> None:
        self.reset_count += 1


def make_session(inputs: list[str]):
    iterator = iter(inputs)
    stream = StringIO()
    approval = InteractiveApproval(lambda message: False)
    agent = FakeAgent()
    session = ChatSession(
        agent=agent,
        approval=approval,
        workspace=Path("/workspace"),
        read_only=False,
        model_name="test-model",
        console=Console(file=stream, force_terminal=False, color_system=None),
        input_function=lambda prompt: next(iterator),
    )
    return session, agent, approval, stream


def test_chat_reuses_agent_context_for_follow_up() -> None:
    session, agent, _, _ = make_session(["first task", "follow up", "/exit"])

    assert session.run() is True
    assert agent.started == ["first task"]
    assert agent.continued == ["follow up"]


def test_new_command_starts_fresh_conversation() -> None:
    session, agent, _, _ = make_session(["first", "/new", "second", "/exit"])

    session.run()

    assert agent.started == ["first", "second"]
    assert agent.continued == []
    assert agent.reset_count == 1


def test_chat_toggles_auto_approval_and_reports_status() -> None:
    session, _, approval, stream = make_session(
        ["/yes on", "/status", "/yes off", "/exit"]
    )

    session.run()

    assert approval.auto_approve is False
    output = stream.getvalue()
    assert "自动审批已开启" in output
    assert "审批：自动" in output
    assert "自动审批已关闭" in output


def test_chat_history_and_help() -> None:
    session, _, _, stream = make_session(["task", "/history", "/help", "/exit"])

    session.run()

    output = stream.getvalue()
    assert "1. task" in output
    assert "/status" in output
