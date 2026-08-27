"""
文件名：cli.py

功能：
提供 PatchPilot 命令行入口，并从工作区外加载凭据。
"""

import os
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console

from patchpilot.agent import Agent, MaxStepsExceeded
from patchpilot.config import ConfigurationError, Settings
from patchpilot.context import ContextManager
from patchpilot.events import RichEventSink
from patchpilot.model import ModelError, OpenAIClient
from patchpilot.prompts import SYSTEM_PROMPT
from patchpilot.tools import (
    ApplyPatchTool,
    ListFilesTool,
    ReadFileTool,
    RunCommandTool,
    SearchTextTool,
    Tool,
    ToolRegistry,
)
from patchpilot.workspace import Workspace


app = typer.Typer(
    name="patchpilot",
    help="一个可以读写文件并执行命令的本地编程智能体。",
    no_args_is_help=True,
)
console = Console()


def configuration_path() -> Path:
    """返回显式配置路径，或用户目录下的默认安全路径。"""

    explicit = os.getenv("PATCHPILOT_CONFIG")
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (Path.home() / ".config" / "patchpilot" / ".env").resolve()


def load_configuration() -> Path:
    """加载外置配置；已有环境变量不会被文件内容覆盖。"""

    path = configuration_path()
    if path.is_file():
        load_dotenv(path, override=False)
    return path


def build_tools(workspace: Workspace, read_only: bool) -> list[Tool]:
    """根据运行模式创建工具；只读模式不注册修改能力。"""

    tools: list[Tool] = [
        ListFilesTool(workspace),
        ReadFileTool(workspace),
        SearchTextTool(workspace),
    ]
    if not read_only:
        tools.extend([ApplyPatchTool(workspace), RunCommandTool(workspace)])
    return tools


def ensure_config_outside_writable_workspace(
    config_path: Path,
    workspace: Workspace,
    read_only: bool,
) -> None:
    """防止命令工具从工作区中直接读取配置文件。"""

    if read_only or not config_path.exists():
        return
    try:
        config_path.relative_to(workspace.root)
    except ValueError:
        return
    raise ConfigurationError(
        "完整模式要求配置文件位于工作区外部；请缩小 --workspace 范围"
    )


@app.callback()
def root() -> None:
    """PatchPilot 命令行根入口。"""


@app.command()
def run(
    task: str = typer.Argument(..., help="需要 Agent 完成的编程任务。"),
    workspace: Path = typer.Option(
        Path("."), "--workspace", "-w",
        help="Agent 可以访问的项目根目录。",
        exists=True, file_okay=False, dir_okay=True, resolve_path=True,
    ),
    max_steps: Optional[int] = typer.Option(
        None, "--max-steps", min=1, max=100,
        help="覆盖环境变量中的最大循环步数。",
    ),
    read_only: bool = typer.Option(
        False, "--read-only",
        help="只允许查看和搜索文件，禁止修改文件或执行命令。",
    ),
) -> None:
    """在指定工作区执行一个编程任务。"""

    if not task.strip():
        console.print("[red]错误：任务内容不能为空。[/red]")
        raise typer.Exit(code=2)

    config_path = load_configuration()
    try:
        settings = Settings.from_env()
        safe_workspace = Workspace(workspace)
        ensure_config_outside_writable_workspace(
            config_path, safe_workspace, read_only
        )
        registry = ToolRegistry(
            build_tools(safe_workspace, read_only),
            max_output_chars=settings.max_tool_output,
        )
        model = OpenAIClient(
            api_key=settings.api_key,
            base_url=settings.base_url,
            model=settings.model,
            timeout=settings.timeout,
        )
        agent = Agent(
            model=model,
            context=ContextManager(SYSTEM_PROMPT),
            tools=registry,
            events=RichEventSink(console),
            max_steps=max_steps or settings.max_steps,
        )
        agent.run(task)
    except ConfigurationError as error:
        console.print(f"[red]配置错误：{error}[/red]")
        raise typer.Exit(code=2) from error
    except MaxStepsExceeded as error:
        console.print(f"[yellow]任务未完成：{error}[/yellow]")
        raise typer.Exit(code=3) from error
    except ModelError as error:
        console.print(f"[red]模型请求失败：{error}[/red]")
        raise typer.Exit(code=4) from error
    except KeyboardInterrupt:
        console.print("\n[yellow]任务已由用户中断。[/yellow]")
        raise typer.Exit(code=130)


def main() -> None:
    """项目安装后的命令行入口。"""

    app()


if __name__ == "__main__":
    main()
