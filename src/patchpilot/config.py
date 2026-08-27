"""
文件名: config.py

功能: 
读取并验证 PatchPilot 的运行配置。

安全要求: 
API Key 只能通过环境变量传入，不能写入代码或提交到 Git 仓库。
"""

import os
from dataclasses import dataclass



class ConfigurationError(Exception):
    """配置错误异常"""
    pass




@dataclass(frozen=True, slots=True)
class Settings:
    """Agent 的不可变运行配置"""

    api_key: str
    base_url: str
    model: str
    timeout: float = 60.0
    max_steps: int = 20
    max_tool_output: int = 20_000


    @classmethod
    def from_env(cls) -> "Settings":
        """从环境变量读取配置"""


        api_key = os.getenv("AGENT_API_KEY", "").strip()
        base_url = os.getenv("AGENT_BASE_URL", "").strip()
        model = os.getenv("AGENT_MODEL", "").strip()

        if not api_key:
            raise ConfigurationError("缺少环境变量 AGENT_API_KEY")

        if not base_url:
            raise ConfigurationError("缺少环境变量 AGENT_BASE_URL")

        if not model:
            raise ConfigurationError("缺少环境变量 AGENT_MODEL")

        try:
            timeout = float(os.getenv("AGENT_TIMEOUT", "60"))
            max_steps = int(os.getenv("AGENT_MAX_STEPS", "20"))
        except ValueError as error:
            raise ConfigurationError(
                "AGENT_TIMEOUT 或 AGENT_MAX_STEPS 格式不正确"
            ) from error

        if timeout <= 0:
            raise ConfigurationError("AGENT_TIMEOUT 必须大于 0")

        if max_steps <= 0:
            raise ConfigurationError("AGENT_MAX_STEPS 必须大于 0")

        return cls(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            model=model,
            timeout=timeout,
            max_steps=max_steps,

        )