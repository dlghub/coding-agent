"""
文件名：model.py

功能：
定义模型客户端协议，并实现 OpenAI-compatible 模型适配器。

安全说明：
异常信息只保留错误类型和状态码，不包含 API Key 或完整请求正文。
"""

import json
import time
from typing import Any, Protocol

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

from patchpilot.schemas import Message, ModelResponse, ToolCall


class ModelError(Exception):
    """模型请求失败。"""


class ModelProtocolError(ModelError):
    """模型响应不符合 PatchPilot 所需协议。"""


class ModelClient(Protocol):
    """Agent 依赖的模型客户端接口。"""

    def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        """发送一次模型请求并返回统一响应。"""


class OpenAIClient:
    """OpenAI-compatible Chat Completions 客户端。"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60.0,
        max_retries: int = 3,
        *,
        client: Any | None = None,
    ) -> None:
        if max_retries < 1:
            raise ValueError("max_retries 必须至少为 1")

        self.model = model
        self.max_retries = max_retries
        # client 参数用于离线测试；生产环境创建真实 SDK 客户端。
        self._client = client or OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,
        )

    def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        """调用模型，并对临时网络错误进行有限指数退避重试。"""

        sdk_messages = [self._encode_message(message) for message in messages]
        for attempt in range(self.max_retries):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=sdk_messages,
                    tools=tools,
                    tool_choice="auto",
                )
                return self._decode_response(response)
            except (RateLimitError, APITimeoutError, APIConnectionError) as error:
                if attempt == self.max_retries - 1:
                    raise ModelError(
                        f"模型请求在 {self.max_retries} 次尝试后仍然失败："
                        f"{type(error).__name__}"
                    ) from error
                time.sleep(2**attempt)
            except APIStatusError as error:
                # 非临时 HTTP 状态错误通常需要修改配置或权限，立即停止。
                raise ModelError(
                    f"模型服务返回 HTTP {error.status_code}"
                ) from error

        raise ModelError("模型请求失败")

    def _encode_message(self, message: Message) -> dict[str, Any]:
        """将内部消息编码为 OpenAI-compatible 消息。"""

        encoded: dict[str, Any] = {
            "role": message.role,
            "content": message.content,
        }
        if message.tool_calls:
            encoded["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        if message.tool_call_id is not None:
            encoded["tool_call_id"] = message.tool_call_id
        return encoded

    def _decode_response(self, response: Any) -> ModelResponse:
        """将第三方 SDK 响应解码为项目内部响应。"""

        if not getattr(response, "choices", None):
            raise ModelProtocolError("模型响应中缺少 choices")

        choice = response.choices[0]
        message = choice.message
        tool_calls: list[ToolCall] = []
        for raw_call in getattr(message, "tool_calls", None) or []:
            raw_arguments = raw_call.function.arguments
            try:
                arguments = json.loads(raw_arguments)
            except (json.JSONDecodeError, TypeError) as error:
                raise ModelProtocolError(
                    f"工具 {raw_call.function.name} 的参数不是合法 JSON"
                ) from error
            if not isinstance(arguments, dict):
                raise ModelProtocolError(
                    f"工具 {raw_call.function.name} 的参数必须是 JSON 对象"
                )
            tool_calls.append(
                ToolCall(
                    id=raw_call.id,
                    name=raw_call.function.name,
                    arguments=arguments,
                )
            )

        return ModelResponse(
            content=getattr(message, "content", None),
            tool_calls=tool_calls,
            finish_reason=getattr(choice, "finish_reason", None),
        )
