"""根据真实工具执行记录生成结构化任务结果。"""

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from patchpilot.schemas import ToolCall, ToolResult


RunStatus = Literal["completed", "partial", "failed"]


@dataclass(frozen=True, slots=True)
class VerificationEvidence:
    """一次可识别验证命令的执行证据。"""

    command: list[str]
    passed: bool
    sequence: int


@dataclass(frozen=True, slots=True)
class RunSummary:
    """不依赖模型自述的任务结果摘要。"""

    status: RunStatus
    changed_files: list[str] = field(default_factory=list)
    verifications: list[VerificationEvidence] = field(default_factory=list)
    verification_current: bool | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class EvidenceCollector:
    """收集成功补丁和验证命令，并计算最终可信状态。"""

    def __init__(self) -> None:
        self._sequence = 0
        self._changes: list[tuple[int, str]] = []
        self._verifications: list[VerificationEvidence] = []

    def record(self, call: ToolCall, result: ToolResult) -> None:
        self._sequence += 1
        if call.name == "apply_patch" and result.ok:
            path = call.arguments.get("path")
            if isinstance(path, str):
                self._changes.append((self._sequence, path))
            return

        if call.name != "run_command" or not result.ok:
            return
        command = self._normalise_command(call.arguments.get("command"))
        if command is None or not self._is_verification(command):
            return
        exit_match = re.search(r"退出码：(-?\d+)", result.output)
        passed = bool(exit_match and int(exit_match.group(1)) == 0)
        self._verifications.append(
            VerificationEvidence(command, passed, self._sequence)
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "sequence": self._sequence,
            "changes": [[sequence, path] for sequence, path in self._changes],
            "verifications": [asdict(item) for item in self._verifications],
        }

    @classmethod
    def restore(cls, snapshot: dict[str, object]) -> "EvidenceCollector":
        collector = cls()
        collector._sequence = int(snapshot.get("sequence", 0))
        collector._changes = [
            (int(item[0]), str(item[1]))
            for item in snapshot.get("changes", [])
        ]
        collector._verifications = [
            VerificationEvidence(
                command=list(item["command"]),
                passed=bool(item["passed"]),
                sequence=int(item["sequence"]),
            )
            for item in snapshot.get("verifications", [])
        ]
        return collector

    def build(
        self,
        forced_status: RunStatus | None = None,
        extra_warning: str | None = None,
    ) -> RunSummary:
        changed_files = list(dict.fromkeys(path for _, path in self._changes))
        warnings: list[str] = []
        verification_current: bool | None = None

        if self._changes:
            latest_change = self._changes[-1][0]
            current_verifications = [
                evidence
                for evidence in self._verifications
                if evidence.sequence > latest_change
            ]
            verification_current = bool(
                current_verifications and current_verifications[-1].passed
            )
            if not self._verifications:
                warnings.append("代码已修改，但没有运行可识别的验证命令。")
            elif not verification_current:
                warnings.append("最后一次修改之后没有成功的验证记录。")
        elif self._verifications:
            verification_current = self._verifications[-1].passed

        if extra_warning:
            warnings.append(extra_warning)

        if forced_status is not None:
            status = forced_status
        elif self._changes and not verification_current:
            status = "partial"
        elif self._verifications and not self._verifications[-1].passed:
            status = "partial"
        else:
            status = "completed"

        return RunSummary(
            status=status,
            changed_files=changed_files,
            verifications=list(self._verifications),
            verification_current=verification_current,
            warnings=warnings,
        )

    @staticmethod
    def _normalise_command(value: object) -> list[str] | None:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return None
        if not isinstance(value, list) or not value:
            return None
        if not all(isinstance(item, str) for item in value):
            return None
        return value

    @staticmethod
    def _is_verification(command: list[str]) -> bool:
        program = Path(command[0]).name.lower()
        direct = {"pytest", "ruff", "mypy"}
        if program in direct:
            return True
        if program in {"python", "python3"} or program.startswith("python3."):
            if len(command) >= 3 and command[1] == "-m":
                return command[2] in {
                    "pytest", "ruff", "mypy", "unittest", "compileall"
                }
        return command[:3] == ["git", "diff", "--check"]
