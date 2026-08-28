"""PatchPilot 持续多轮终端对话会话。"""

from collections.abc import Callable
from pathlib import Path

from rich.console import Console

from patchpilot.agent import Agent, MaxStepsExceeded
from patchpilot.approvals import InteractiveApproval
from patchpilot.model import ModelError


InputFunction = Callable[[str], str]
StatusFunction = Callable[[], str]


HELP_TEXT = """可用命令：
  /help          显示帮助
  /status        显示当前工作区、模式和上下文状态
  /new           清空上下文，开始新对话
  /history       显示本次终端会话输入历史
  /yes on|off    开启或关闭普通操作自动审批
  /clear         清空终端显示
  /exit          退出对话模式

其他输入都会作为编码需求发送给 PatchPilot。"""


class ChatSession:
    """读取用户输入并在同一个 Agent 上连续执行多轮任务。"""

    def __init__(
        self,
        agent: Agent,
        approval: InteractiveApproval,
        workspace: Path,
        read_only: bool,
        model_name: str,
        console: Console | None = None,
        input_function: InputFunction = input,
        status_function: StatusFunction | None = None,
    ) -> None:
        self.agent = agent
        self.approval = approval
        self.workspace = workspace
        self.read_only = read_only
        self.model_name = model_name
        self.console = console or Console()
        self.input_function = input_function
        self.status_function = status_function
        self.started = False
        self.last_turn_completed = True
        self.history: list[str] = []

    def run(self) -> bool:
        """运行到 /exit 或输入结束；返回最后一轮是否正常完成。"""

        self.console.print("\n[bold cyan]PatchPilot Chat[/bold cyan]")
        self.console.print(f"工作区：{self.workspace}", markup=False)
        self.console.print("输入 /help 查看命令，输入 /exit 退出。", style="dim")
        while True:
            try:
                text = self.input_function("你 > ").strip()
            except (EOFError, KeyboardInterrupt):
                self.console.print(
                    "\n输入流中断；如存在 checkpoint，将予以保留。",
                    style="yellow",
                )
                return False
            if not text:
                continue
            if text.startswith("/"):
                should_exit = self._handle_command(text)
                if should_exit:
                    return self.last_turn_completed
                continue

            self.history.append(text)
            self.last_turn_completed = False
            first_turn = not self.started
            self.started = True
            try:
                if first_turn:
                    self.agent.run(text)
                else:
                    self.agent.continue_with(text)
                self.last_turn_completed = True
            except MaxStepsExceeded as error:
                self.console.print(f"任务未完成：{error}", style="yellow")
            except ModelError as error:
                self.console.print(f"模型请求失败：{error}", style="red")
            except KeyboardInterrupt:
                self.console.print("本轮已中断，可以输入继续要求或 /exit。", style="yellow")

    def _handle_command(self, text: str) -> bool:
        parts = text.split()
        command = parts[0].lower()
        if command in {"/exit", "/quit"}:
            if not self.last_turn_completed:
                self.console.print("最后一轮未完成，checkpoint 将保留。", style="yellow")
            else:
                self.console.print("已退出 PatchPilot Chat。", style="green")
            return True
        if command == "/help":
            self.console.print(HELP_TEXT)
        elif command == "/status":
            self.console.print(self._status(), markup=False)
        elif command == "/new":
            self.agent.reset_conversation()
            self.started = False
            self.last_turn_completed = True
            self.console.print("已清空对话上下文；下一条输入将开始新对话。")
        elif command == "/history":
            if not self.history:
                self.console.print("本次会话还没有普通输入。")
            for index, item in enumerate(self.history, 1):
                self.console.print(f"{index}. {item}", markup=False)
        elif command == "/yes":
            self._set_auto_approval(parts)
        elif command == "/clear":
            self.console.clear()
        else:
            self.console.print(f"未知命令：{command}；输入 /help 查看帮助。", style="yellow")
        return False

    def _set_auto_approval(self, parts: list[str]) -> None:
        if len(parts) != 2 or parts[1].lower() not in {"on", "off"}:
            self.console.print("用法：/yes on 或 /yes off", style="yellow")
            return
        self.approval.auto_approve = parts[1].lower() == "on"
        state = "开启" if self.approval.auto_approve else "关闭"
        self.console.print(f"自动审批已{state}。")

    def _status(self) -> str:
        mode = "只读" if self.read_only else "完整"
        approval = "自动" if self.approval.auto_approve else "逐次确认"
        base = (
            f"工作区：{self.workspace}\n"
            f"模型：{self.model_name}\n"
            f"模式：{mode}\n"
            f"审批：{approval}\n"
            f"已输入需求：{len(self.history)}"
        )
        return base + (f"\n{self.status_function()}" if self.status_function else "")
