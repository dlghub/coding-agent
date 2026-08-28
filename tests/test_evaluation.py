"""离线验证评测用例发现、隔离复制和指标计算。"""

import json
from pathlib import Path

from patchpilot.evaluation import (
    AgentExecution,
    CommandExecution,
    EvaluationRunner,
    metrics_from_output,
)


def make_case(root: Path) -> Path:
    case = root / "bug"
    workspace = case / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "value.txt").write_text("broken", encoding="utf-8")
    (case / "case.json").write_text(
        json.dumps(
            {
                "name": "simple-bug",
                "task": "fix value",
                "test_command": ["python", "-m", "unittest"],
            }
        ),
        encoding="utf-8",
    )
    return root


def test_evaluation_runner_scores_fixed_case_and_cleans_workspace(tmp_path) -> None:
    seen_workspace = None

    def command_executor(command, workspace):
        return CommandExecution(
            passed=(workspace / "value.txt").read_text(encoding="utf-8") == "fixed"
        )

    def agent_executor(task, workspace):
        nonlocal seen_workspace
        seen_workspace = workspace
        (workspace / "value.txt").write_text("fixed", encoding="utf-8")
        return AgentExecution(0, 0.25, steps=3, tool_calls=2)

    report = EvaluationRunner(agent_executor, command_executor).run(
        make_case(tmp_path / "cases")
    )

    assert report.total == 1
    assert report.passed == 1
    assert report.success_rate == 1.0
    assert report.results[0].baseline_failed is True
    assert report.results[0].steps == 3
    assert seen_workspace is not None and not seen_workspace.exists()


def test_evaluation_can_keep_failed_workspace(tmp_path) -> None:
    work_root = tmp_path / "kept"
    runner = EvaluationRunner(
        lambda task, workspace: AgentExecution(4, 0.1),
        lambda command, workspace: CommandExecution(False, "failed"),
        keep_workspaces=True,
        work_root=work_root,
    )

    report = runner.run(make_case(tmp_path / "cases"))

    assert report.results[0].success is False
    assert (work_root / "simple-bug" / "value.txt").is_file()


def test_metrics_from_cli_output() -> None:
    output = "Step 1/20\n→ 调用工具 read_file\nStep 4/20\n→ 调用工具 apply_patch"
    assert metrics_from_output(output) == (4, 2)
