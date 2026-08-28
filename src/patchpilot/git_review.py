"""在任务结束时执行只读、无 shell 的 Git 工作树审查。"""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GitReview:
    """Git 状态、差异规模和格式检查结果。"""

    available: bool
    status_lines: list[str] = field(default_factory=list)
    diff_stat: str = ""
    diff_check_passed: bool | None = None
    error: str | None = None


class GitInspector:
    """只审查 workspace 自身的 Git 仓库，不向上查找父仓库。"""

    def __init__(
        self,
        workspace: Path,
        timeout: int = 15,
        max_output_chars: int = 8_000,
        max_status_lines: int = 200,
    ) -> None:
        self.workspace = workspace
        self.timeout = timeout
        self.max_output_chars = max_output_chars
        self.max_status_lines = max_status_lines

    def inspect(self) -> GitReview:
        if not (self.workspace / ".git").exists():
            return GitReview(available=False)
        try:
            status = self._run(
                ["git", "status", "--short", "--untracked-files=all"]
            )
            unstaged_stat = self._run(["git", "diff", "--stat"])
            staged_stat = self._run(["git", "diff", "--cached", "--stat"])
            unstaged_check = self._run(["git", "diff", "--check"], check=False)
            staged_check = self._run(
                ["git", "diff", "--cached", "--check"], check=False
            )
        except (OSError, subprocess.SubprocessError) as error:
            return GitReview(
                available=True,
                error=f"Git 审查失败：{type(error).__name__}",
            )

        status_lines = status.stdout.splitlines()
        if len(status_lines) > self.max_status_lines:
            omitted = len(status_lines) - self.max_status_lines
            status_lines = status_lines[: self.max_status_lines]
            status_lines.append(f"... 另有 {omitted} 个状态条目未显示")

        stat_parts = []
        if unstaged_stat.stdout.strip():
            stat_parts.append("未暂存：\n" + unstaged_stat.stdout.strip())
        if staged_stat.stdout.strip():
            stat_parts.append("已暂存：\n" + staged_stat.stdout.strip())
        diff_stat = "\n".join(stat_parts)
        if len(diff_stat) > self.max_output_chars:
            diff_stat = diff_stat[: self.max_output_chars] + "\n[差异统计已截断]"

        return GitReview(
            available=True,
            status_lines=status_lines,
            diff_stat=diff_stat,
            diff_check_passed=(
                unstaged_check.returncode == 0 and staged_check.returncode == 0
            ),
        )

    def _run(
        self,
        command: list[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            command,
            cwd=self.workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=self.timeout,
            check=False,
        )
        if check and completed.returncode != 0:
            raise subprocess.CalledProcessError(
                completed.returncode, command, completed.stdout, completed.stderr
            )
        return completed
