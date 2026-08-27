"""
文件名: model.py

功能：
定义模型客户端接口，并实现 OpenAI-compatible 模型客户端。

设计说明：
其他模块只能依赖 ModelClient 协议和内部 ModelResponse, 
不能直接依赖 OpenAI SDK 返回的数据结构。
"""

from calendar import c
import json
from operator import call
import time
from typing import Any, Protocol

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)
from sympy import li

from patchpilot.schemas import ModelResponse, Message, ToolCall


class ModelError(Exception):
    """模型请求异常"""
    pass


class ModelProtocol(ModelError):
    """模型协议异常"""
    pass


class ModelClient(Protocol):
    """模型客户端接口"""

    def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        """向模型发起一次请求，返回统一的响应格式"""
        pass


class OpenAIClient:
    """OpenAI-compatible 模型客户端"""

    def __init__(
        self, 
        api_key: str, 
        base_url: str, 
        model: str, 
        timeout: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        self.model = model
        self.max_retries = max_retries

        # 关闭 SDK 的自动重试，使用自定义的重试逻辑
        self._client = OpenAI(
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
        """向模型发起一次请求，返回统一的响应格式"""

        sdk_messages = [self._encode_message(m) for m in messages]

        for attempt in range(self.max_retries):
            try:
                reponse = self._client.chat.completions.create(
                    model=self.model,
                    messages=sdk_messages,
                    tools=tools,
                    tool_choice="auto",
                )

                return self._decode_response(reponse)

            except (RateLimitError, APITimeoutError, APIConnectionError) as error:
                if attempt == self.max_retries - 1:
                    raise ModelError("模型请求失败，达到最大重试次数") from error

                # 使用 1 2 4 8 ... 的指数退避策略
                delay = 2 ** attempt
                time.sleep(delay)

            except APIStatusError as error:
                raise ModelError(f"模型请求失败，HTTP 状态码: {error.http_status}") from error

        raise ModelError("模型请求失败")


    def _encode_message(self, message: Message) -> dict[str, Any]:
        """将内部 Message 转换为 OpenAI-compatible 消息格式"""

        encoded: dict[str, Any] = {
            "role": message.role,
            "content": message.content,
        }

        if message.tool_calls:
            encoded["tool_calls"] = [
                {
                    "id": call.id,
                    "type": function,
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            call.arguments,
                            ensure_ascii=False,
                        ),
                    },
                }
                for call in message.tool_calls
            ]

        if message.tool_call_id is not None:
            encoded["tool_call_id"] = message.tool_call_id

        return encoded


    def _decode_response(self, reponse: Any) -> ModelResponse:
        """将 SDK 返回的响应解码为统一的内部格式"""

        if not reponse.choices:
            raise ModelProtocol("模型响应中缺少 choices 字段")

        choice = reponse.choices[0]
        message = choice.message
        tool_calls: list[ToolCall] = []

        for raw_call in message.tool_calls or []:
            try:
                arguments = json.loads(raw_call.function.arguments)
            except json.JSONDecodeError as error:
                raise ModelProtocol(
                    f"工具调用参数不是合法的 JSON: {raw_call.function.arguments}"
                ) from error

            if not isinstance(arguments, dict):
                raise ModelProtocol(
                    f"工具调用参数不是 JSON 对象: {raw_call.function.arguments}"
                )

            tool_calls.append(
                ToolCall(
                    id=raw_call.id,
                    name=raw_call.function.name,
                    arguments=arguments,
                )
            )

        return ModelResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
        )
        