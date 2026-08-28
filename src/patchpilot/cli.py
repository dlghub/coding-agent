"""
文件名：cli.py

功能：
组装配置、审批、会话日志、工具、模型和 Agent。
"""

import os
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console

from patchpilot.agent import Agent, MaxStepsExceeded
from patchpilot.approvals import InteractiveApproval
from patchpilot.checkpoint import CheckpointError, CheckpointStore
from patchpilot.config import ConfigurationError, Settings
from patchpilot.context import ContextManager
from patchpilot.events import CompositeEventSink, JsonlEventSink, RichEventSink
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


def session_directory() -> Path:
    return Path.home() / ".local" / "state" / "patchpilot" / "sessions"


def configuration_path() -> Path:
    explicit = os.getenv("PATCHPILOT_CONFIG")
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (Path.home() / ".config" / "patchpilot" / ".env").resolve()


def load_configuration() -> Path:
    path = configuration_path()
    if path.is_file():
        load_dotenv(path, override=False)
    return path


def build_tools(workspace: Workspace, read_only: bool) -> list[Tool]:
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
    if read_only or not config_path.exists():
        return
    try:
        config_path.relative_to(workspace.root)
    except ValueError:
        return
    raise ConfigurationError(
        "完整模式要求配置文件位于工作区外部；请缩小 --workspace 范围"
    )


def confirm_action(message: str) -> bool:
    """在终端展示操作摘要并请求用户确认。"""

    console.print("\n需要审批", style="bold yellow")
    console.print(message, markup=False)
    return typer.confirm("是否允许", default=False)


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
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="自动批准可审批操作；硬性禁止规则仍然生效。",
    ),
    no_log: bool = typer.Option(
        False, "--no-log",
        help="不写入本次运行的 JSONL 会话日志。",
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
        ensure_config_outside_writable_workspace(config_path, safe_workspace, read_only)

        approval = InteractiveApproval(confirm_action, auto_approve=yes)
        registry = ToolRegistry(
            build_tools(safe_workspace, read_only),
            max_output_chars=settings.max_tool_output,
            approval=approval,
        )

        sinks = [RichEventSink(console)]
        session_log = None
        checkpoint_store = None
        if not no_log:
            session_log = JsonlEventSink(safe_workspace.root, read_only)
            sinks.append(session_log)
            console.print(f"会话日志：{session_log.path}", style="dim", markup=False)
            checkpoint_store = CheckpointStore(
                session_log.path.with_suffix(".checkpoint.json"),
                safe_workspace.root,
                read_only,
            )

        event_sink = CompositeEventSink(sinks)
        model = OpenAIClient(
            api_key=settings.api_key,
            base_url=settings.base_url,
            model=settings.model,
            timeout=settings.timeout,
            retry_callback=event_sink.model_retrying,
        )
        agent = Agent(
            model=model,
            context=ContextManager(
                SYSTEM_PROMPT,
                max_context_chars=settings.max_context_chars,
            ),
            tools=registry,
            events=event_sink,
            max_steps=max_steps or settings.max_steps,
            checkpoint_callback=(
                checkpoint_store.save if checkpoint_store is not None else None
            ),
        )
        agent.run(task)
        if checkpoint_store is not None:
            checkpoint_store.remove()
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


@app.command()
def resume(
    session_id: str = typer.Argument(
        ..., help="会话日志文件 stem 或其中的 session 短 ID。"
    ),
    max_steps: Optional[int] = typer.Option(
        None, "--max-steps", min=1, max=100,
        help="本次恢复可使用的新步骤数。",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="自动批准可审批操作；硬性禁止规则仍然生效。",
    ),
    no_log: bool = typer.Option(
        False, "--no-log",
        help="本次继续执行不创建新日志和恢复点。",
    ),
) -> None:
    """从异常退出时保存的 checkpoint 继续任务。"""

    source_store: CheckpointStore | None = None
    new_store: CheckpointStore | None = None
    try:
        source_path = CheckpointStore.find(session_id, session_directory())
        source_store = CheckpointStore(source_path, Path("."), False)
        checkpoint = source_store.load()

        config_path = load_configuration()
        settings = Settings.from_env()
        safe_workspace = Workspace(Path(checkpoint.workspace))
        ensure_config_outside_writable_workspace(
            config_path, safe_workspace, checkpoint.read_only
        )
        approval = InteractiveApproval(confirm_action, auto_approve=yes)
        registry = ToolRegistry(
            build_tools(safe_workspace, checkpoint.read_only),
            max_output_chars=settings.max_tool_output,
            approval=approval,
        )

        sinks = [RichEventSink(console)]
        if not no_log:
            session_log = JsonlEventSink(
                safe_workspace.root, checkpoint.read_only
            )
            sinks.append(session_log)
            new_store = CheckpointStore(
                session_log.path.with_suffix(".checkpoint.json"),
                safe_workspace.root,
                checkpoint.read_only,
            )
            console.print(
                f"新会话日志：{session_log.path}", style="dim", markup=False
            )
        console.print(f"恢复来源：{source_path.name}", style="dim", markup=False)

        event_sink = CompositeEventSink(sinks)
        model = OpenAIClient(
            api_key=settings.api_key,
            base_url=settings.base_url,
            model=settings.model,
            timeout=settings.timeout,
            retry_callback=event_sink.model_retrying,
        )
        agent = Agent(
            model=model,
            context=ContextManager(
                SYSTEM_PROMPT,
                max_context_chars=settings.max_context_chars,
            ),
            tools=registry,
            events=event_sink,
            max_steps=max_steps or settings.max_steps,
            checkpoint_callback=new_store.save if new_store else None,
        )
        agent.resume(checkpoint.state)
        source_store.remove()
        if new_store is not None:
            new_store.remove()
    except (CheckpointError, ConfigurationError, ValueError) as error:
        console.print(f"[red]恢复失败：{error}[/red]")
        raise typer.Exit(code=2) from error
    except MaxStepsExceeded as error:
        console.print(f"[yellow]任务未完成：{error}[/yellow]")
        raise typer.Exit(code=3) from error
    except ModelError as error:
        console.print(f"[red]模型请求失败：{error}[/red]")
        raise typer.Exit(code=4) from error
    except KeyboardInterrupt:
        console.print("\n[yellow]任务已由用户中断，恢复点已保留。[/yellow]")
        raise typer.Exit(code=130)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
