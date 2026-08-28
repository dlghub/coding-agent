"""为 run_command 构造无网络、资源受限的 Docker 执行边界。"""

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


class SandboxConfigurationError(ValueError):
    """沙箱配置不安全或当前平台不支持。"""


@dataclass(frozen=True, slots=True)
class DockerInvocation:
    command: list[str]
    container_name: str


class DockerSandbox:
    """把 workspace 作为容器中唯一可写的持久目录。"""

    def __init__(
        self,
        workspace: Path,
        image: str = "ubuntu:22.04",
        runtime_prefix: Path | None = None,
    ) -> None:
        if os.name != "posix":
            raise SandboxConfigurationError("Docker 沙箱当前只支持 Linux/WSL")
        if not re.fullmatch(r"[A-Za-z0-9._/@:-]+", image) or image.startswith("-"):
            raise SandboxConfigurationError("AGENT_SANDBOX_IMAGE 格式不安全")
        self.workspace = workspace.resolve()
        self.image = image
        self.runtime_prefix = (runtime_prefix or Path(sys.prefix)).resolve()
        if "," in str(self.workspace) or "," in str(self.runtime_prefix):
            raise SandboxConfigurationError("Docker 挂载路径不能包含逗号")

    def wrap(self, command: list[str]) -> DockerInvocation:
        name = f"patchpilot-{uuid4().hex[:12]}"
        wrapped = [
            "docker", "run", "--rm", "--pull", "never", "--name", name,
            "--network", "none", "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", "128", "--memory", "512m", "--cpus", "1",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--mount", self._mount(self.workspace, Path("/workspace")),
        ]
        for system_path in (Path("/usr"), Path("/lib"), Path("/lib64")):
            if system_path.exists():
                wrapped.extend(
                    ["--mount", self._mount(system_path, system_path, True)]
                )
        if self.runtime_prefix.exists():
            wrapped.extend(
                [
                    "--mount",
                    self._mount(self.runtime_prefix, self.runtime_prefix, True),
                ]
            )
        runtime_bin = str(self.runtime_prefix / "bin")
        wrapped.extend(
            [
                "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=67108864",
                "--workdir", "/workspace",
                "--env", "HOME=/tmp",
                "--env", f"PATH={runtime_bin}:/usr/local/sbin:/usr/local/bin:"
                "/usr/sbin:/usr/bin:/sbin:/bin",
                "--env", "PYTHONDONTWRITEBYTECODE=1",
                "--env", "PYTHONUNBUFFERED=1",
                self.image,
                *command,
            ]
        )
        return DockerInvocation(wrapped, name)

    @staticmethod
    def cleanup_command(container_name: str) -> list[str]:
        return ["docker", "rm", "-f", container_name]

    @staticmethod
    def _mount(source: Path, target: Path, read_only: bool = False) -> str:
        value = f"type=bind,source={source},target={target}"
        return value + (",readonly" if read_only else "")
