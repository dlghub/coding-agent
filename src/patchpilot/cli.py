"""
文件名：cli.py

功能：
提供 PatchPilot 命令行入口，并组装模型、上下文、工具和 Agent。
"""

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
    ToolRegistry,
)
from patchpilot.workspace import Workspace


app = typer.Typer(
    name="patchpilot",
    help="一个可以读写文件并执行命令的本地编程智能体。",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def root() -> None:
    """PatchPilot 命令行根入口。"""


@app.command()
def run(
    task: str = typer.Argument(..., help="需要 Agent 完成的编程任务。"),
    workspace: Path = typer.Option(
        Path("."),
        "--workspace",
        "-w",
        help="Agent 可以访问的项目根目录。",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    max_steps: Optional[int] = typer.Option(
        None,
        "--max-steps",
        min=1,
        max=100,
        help="覆盖环境变量中的最大循环步数。",
    ),
) -> None:
    """在指定工作区执行一个编程任务。"""

    if not task.strip():
        console.print("[red]错误：任务内容不能为空。[/red]")
        raise typer.Exit(code=2)

    load_dotenv()
    try:
        settings = Settings.from_env()
        safe_workspace = Workspace(workspace)
        registry = ToolRegistry(
            [
                ListFilesTool(safe_workspace),
                ReadFileTool(safe_workspace),
                SearchTextTool(safe_workspace),
                ApplyPatchTool(safe_workspace),
                RunCommandTool(safe_workspace),
            ],
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
