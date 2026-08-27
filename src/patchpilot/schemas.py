"""
文件名: schemas.py

功能: 
定义 PatchPilot 内部使用的核心数据结构。

设计说明:
模型供应商返回的数据格式不应该直接扩散到整个项目中。
这里定义统一的内部格式，使 Agent、工具系统和模型客户端之间保持低耦合。
"""

from dataclasses import dataclass, field
from json import tool
from typing import Any, Literal

from matplotlib.pyplot import cla


# 限制合法消息角色, 帮助类型检查器发现错误
Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolCall:
    """表示模型发起的一次工具调用"""

    id: str
    name: str
    arguments: dict[str, Any]



@dataclass
class Message:
    """表示 Agent 对话历史中的一条消息"""

    role: Role
    content: str | None = None

    # assistant 消息可能同时包含多个工具调用
    tool_calls: list[ToolCall] = field(default_factory=list)

    # tool 消息通过该字段关联对应的工具调用
    tool_call_id: str | None = None



@dataclass
class ModelResponse:
    """模型客户端返回给 Agent 的统一响应格式"""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None



@dataclass
class ToolResult:
    """一次工具执行的结果"""

    call_id: str
    tool_name: str
    ok: bool
    output: str
    metadata: dict[str, Any] = field(default_factory=dict)