"""
文件名：test_model.py

功能：
离线验证 OpenAI-compatible 消息编码、响应解析与重试策略。
"""

from types import SimpleNamespace

import httpx
import pytest
from openai import APIStatusError, APITimeoutError

from patchpilot.model import ModelError, ModelProtocolError, OpenAIClient
from patchpilot.schemas import Message, ToolCall


def namespace(**values):
    """创建模拟 SDK 对象。"""

    return SimpleNamespace(**values)


def response(content="done", tool_calls=None, finish_reason="stop"):
    """创建模拟 Chat Completions 响应。"""

    return namespace(
        choices=[
            namespace(
                message=namespace(content=content, tool_calls=tool_calls),
                finish_reason=finish_reason,
            )
        ]
    )


class FakeCompletions:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_client(outcomes, max_retries=3):
    completions = FakeCompletions(outcomes)
    sdk = namespace(chat=namespace(completions=completions))
    client = OpenAIClient("secret", "https://example.test/v1", "test-model", max_retries=max_retries, client=sdk)
    return client, completions


def test_encodes_tool_calls_and_tool_result() -> None:
    client, completions = make_client([response()])
    messages = [
        Message(
            role="assistant",
            tool_calls=[ToolCall("call-1", "read_file", {"path": "中文.py"})],
        ),
        Message(role="tool", content="ok", tool_call_id="call-1"),
    ]
    client.complete(messages, [])
    encoded = completions.calls[0]["messages"]
    assert encoded[0]["tool_calls"][0]["function"]["name"] == "read_file"
    assert "中文.py" in encoded[0]["tool_calls"][0]["function"]["arguments"]
    assert encoded[1]["tool_call_id"] == "call-1"


def test_decodes_text_and_multiple_tool_calls() -> None:
    calls = [
        namespace(id="1", function=namespace(name="read_file", arguments='{"path":"a.py"}')),
        namespace(id="2", function=namespace(name="search_text", arguments='{"query":"main"}')),
    ]
    client, _ = make_client([response(content=None, tool_calls=calls, finish_reason="tool_calls")])
    result = client.complete([Message(role="user", content="inspect")], [])
    assert [call.name for call in result.tool_calls] == ["read_file", "search_text"]
    assert result.tool_calls[0].arguments == {"path": "a.py"}
    assert result.finish_reason == "tool_calls"


@pytest.mark.parametrize("arguments", ["not-json", "[]", "null"])
def test_rejects_invalid_tool_arguments(arguments: str) -> None:
    call = namespace(id="1", function=namespace(name="read_file", arguments=arguments))
    client, _ = make_client([response(content=None, tool_calls=[call])])
    with pytest.raises(ModelProtocolError):
        client.complete([Message(role="user", content="inspect")], [])


def test_rejects_empty_choices() -> None:
    client, _ = make_client([namespace(choices=[])])
    with pytest.raises(ModelProtocolError, match="choices"):
        client.complete([Message(role="user", content="inspect")], [])


def test_retries_timeout_then_succeeds(monkeypatch) -> None:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    timeout = APITimeoutError(request=request)
    client, completions = make_client([timeout, response(content="ok")])
    sleeps = []
    monkeypatch.setattr("patchpilot.model.time.sleep", sleeps.append)
    result = client.complete([Message(role="user", content="hello")], [])
    assert result.content == "ok"
    assert len(completions.calls) == 2
    assert sleeps == [1]


def test_stops_after_retry_limit(monkeypatch) -> None:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    client, _ = make_client(
        [APITimeoutError(request=request), APITimeoutError(request=request)],
        max_retries=2,
    )
    monkeypatch.setattr("patchpilot.model.time.sleep", lambda _: None)
    with pytest.raises(ModelError, match="2 次"):
        client.complete([Message(role="user", content="hello")], [])


def test_does_not_retry_non_transient_http_error() -> None:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response_401 = httpx.Response(401, request=request)
    error = APIStatusError("unauthorized", response=response_401, body=None)
    client, completions = make_client([error])
    with pytest.raises(ModelError, match="HTTP 401"):
        client.complete([Message(role="user", content="hello")], [])
    assert len(completions.calls) == 1


def test_rejects_invalid_retry_count() -> None:
    with pytest.raises(ValueError, match="至少为 1"):
        OpenAIClient("key", "https://example.test/v1", "model", max_retries=0)
