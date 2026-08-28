"""端到端编码任务评测：隔离复制、基线验证、Agent 执行和结果计分。"""

import json
import re
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable


class EvaluationError(Exception):
    """评测用例或执行环境不符合要求。"""


@dataclass(frozen=True, slots=True)
class EvalCase:
    name: str
    task: str
    source: Path
    test_command: list[str]


@dataclass(frozen=True, slots=True)
class AgentExecution:
    returncode: int
    duration_seconds: float
    steps: int = 0
    tool_calls: int = 0
    output_tail: str = ""


@dataclass(frozen=True, slots=True)
class CommandExecution:
    passed: bool
    output_tail: str = ""


@dataclass(frozen=True, slots=True)
class CaseResult:
    name: str
    success: bool
    baseline_failed: bool
    verification_passed: bool
    agent_returncode: int
    steps: int
    tool_calls: int
    duration_seconds: float
    workspace: str | None = None
    agent_output_tail: str = ""
    verification_output_tail: str = ""


@dataclass(frozen=True, slots=True)
class EvalReport:
    total: int
    passed: int
    success_rate: float
    total_duration_seconds: float
    results: list[CaseResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


AgentExecutor = Callable[[str, Path], AgentExecution]
CommandExecutor = Callable[[list[str], Path], CommandExecution]


class EvaluationRunner:
    """运行一组本地、可复现的编码修复用例。"""

    def __init__(
        self,
        agent_executor: AgentExecutor,
        command_executor: CommandExecutor,
        keep_workspaces: bool = False,
        work_root: Path | None = None,
    ) -> None:
        self.agent_executor = agent_executor
        self.command_executor = command_executor
        self.keep_workspaces = keep_workspaces
        self.work_root = work_root

    def run(self, cases_root: Path) -> EvalReport:
        cases = self.load_cases(cases_root)
        started = time.monotonic()
        results = [self._run_case(case) for case in cases]
        passed = sum(result.success for result in results)
        duration = time.monotonic() - started
        return EvalReport(
            total=len(results),
            passed=passed,
            success_rate=passed / len(results) if results else 0.0,
            total_duration_seconds=round(duration, 3),
            results=results,
        )

    @staticmethod
    def load_cases(cases_root: Path) -> list[EvalCase]:
        cases: list[EvalCase] = []
        for manifest in sorted(cases_root.glob("*/case.json")):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                command = data["test_command"]
                workspace = manifest.parent / "workspace"
                if not workspace.is_dir():
                    raise EvaluationError(f"缺少 workspace：{manifest.parent.name}")
                if not isinstance(command, list) or not command or not all(
                    isinstance(item, str) and item for item in command
                ):
                    raise EvaluationError(f"test_command 无效：{manifest}")
                cases.append(
                    EvalCase(
                        name=str(data.get("name") or manifest.parent.name),
                        task=str(data["task"]),
                        source=workspace,
                        test_command=command,
                    )
                )
            except (OSError, KeyError, json.JSONDecodeError) as error:
                raise EvaluationError(f"无法加载用例：{manifest}") from error
        if not cases:
            raise EvaluationError(f"没有找到评测用例：{cases_root}")
        return cases

    def _run_case(self, case: EvalCase) -> CaseResult:
        if self.keep_workspaces:
            root = self.work_root or Path("eval-results") / "workspaces"
            root.mkdir(parents=True, exist_ok=True)
            workspace = root / case.name
            if workspace.exists():
                shutil.rmtree(workspace)
            shutil.copytree(case.source, workspace)
        else:
            temporary = Path(tempfile.mkdtemp(prefix=f"patchpilot-eval-{case.name}-"))
            workspace = temporary / "workspace"
            shutil.copytree(case.source, workspace)

        try:
            baseline = self.command_executor(case.test_command, workspace)
            agent = self.agent_executor(case.task, workspace)
            verification = self.command_executor(case.test_command, workspace)
            success = (
                not baseline.passed
                and agent.returncode == 0
                and verification.passed
            )
            return CaseResult(
                name=case.name,
                success=success,
                baseline_failed=not baseline.passed,
                verification_passed=verification.passed,
                agent_returncode=agent.returncode,
                steps=agent.steps,
                tool_calls=agent.tool_calls,
                duration_seconds=round(agent.duration_seconds, 3),
                workspace=str(workspace) if self.keep_workspaces else None,
                agent_output_tail=agent.output_tail,
                verification_output_tail=verification.output_tail,
            )
        finally:
            if not self.keep_workspaces:
                shutil.rmtree(workspace.parent, ignore_errors=True)


def metrics_from_output(output: str) -> tuple[int, int]:
    """从稳定的 CLI 标记提取最大步骤号和工具调用次数。"""

    steps = [int(value) for value in re.findall(r"Step (\d+)/\d+", output)]
    return (max(steps, default=0), output.count("→ 调用工具"))


def output_tail(output: str, limit: int = 4_000) -> str:
    return output[-limit:]
