"""验证 Docker 沙箱命令的安全边界参数。"""

from pathlib import Path

import pytest

from patchpilot.sandbox import DockerSandbox, SandboxConfigurationError


def test_docker_sandbox_wraps_command_with_security_limits(tmp_path: Path) -> None:
    runtime = tmp_path / "venv"
    runtime.mkdir()
    sandbox = DockerSandbox(tmp_path, runtime_prefix=runtime)

    invocation = sandbox.wrap(["python", "-m", "pytest", "-q"])
    command = invocation.command

    assert command[:2] == ["docker", "run"]
    assert ["--network", "none"] == command[
        command.index("--network") : command.index("--network") + 2
    ]
    assert "--read-only" in command
    # 当前 WSL/Docker 组合在覆盖 /usr 后无法找到 /sbin/docker-init。
    # 超时场景由 RunCommandTool 使用容器名进行精确清理。
    assert "--init" not in command
    assert ["--cap-drop", "ALL"] == command[
        command.index("--cap-drop") : command.index("--cap-drop") + 2
    ]
    assert "no-new-privileges" in command
    assert ["--pull", "never"] == command[
        command.index("--pull") : command.index("--pull") + 2
    ]
    assert command[-4:] == ["python", "-m", "pytest", "-q"]
    assert str(tmp_path.resolve()) in " ".join(command)
    assert invocation.container_name.startswith("patchpilot-")


def test_docker_sandbox_rejects_option_like_image(tmp_path: Path) -> None:
    with pytest.raises(SandboxConfigurationError, match="IMAGE"):
        DockerSandbox(tmp_path, image="--privileged")


def test_cleanup_targets_only_generated_container(tmp_path: Path) -> None:
    sandbox = DockerSandbox(tmp_path)
    invocation = sandbox.wrap(["python", "--version"])

    assert DockerSandbox.cleanup_command(invocation.container_name) == [
        "docker", "rm", "-f", invocation.container_name
    ]
