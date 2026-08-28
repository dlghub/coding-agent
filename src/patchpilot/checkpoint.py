"""保存和加载权限受限的 Agent 恢复点。"""

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


class CheckpointError(Exception):
    """恢复点不存在、损坏或版本不兼容。"""


@dataclass(slots=True)
class AgentState:
    """恢复 Agent 所需的内部状态。"""

    task: str
    context: dict[str, object]
    failed_calls: dict[str, list[object]]
    evidence: dict[str, object]


@dataclass(slots=True)
class Checkpoint:
    """包含工作区元数据的磁盘恢复点。"""

    version: int
    workspace: str
    read_only: bool
    state: AgentState


class CheckpointStore:
    """使用原子写入维护单个 JSON checkpoint。"""

    VERSION = 1

    def __init__(self, path: Path, workspace: Path, read_only: bool) -> None:
        self.path = path
        self.workspace = workspace
        self.read_only = read_only

    def save(self, state: AgentState) -> None:
        payload = {
            "version": self.VERSION,
            "workspace": str(self.workspace),
            "read_only": self.read_only,
            "state": asdict(state),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = stream.name
                json.dump(payload, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def load(self) -> Checkpoint:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("version") != self.VERSION:
                raise CheckpointError("恢复点版本不兼容")
            raw_state = payload["state"]
            state = AgentState(
                task=raw_state["task"],
                context=raw_state["context"],
                failed_calls=raw_state["failed_calls"],
                evidence=raw_state["evidence"],
            )
            return Checkpoint(
                version=payload["version"],
                workspace=payload["workspace"],
                read_only=payload["read_only"],
                state=state,
            )
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise CheckpointError(f"无法读取恢复点：{self.path}") from error

    def remove(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    @classmethod
    def find(cls, identifier: str, directory: Path) -> Path:
        """按完整文件名、日志 stem 或其中的 session 短 ID 查找。"""

        safe_identifier = Path(identifier).name
        if (
            safe_identifier != identifier
            or not re.fullmatch(r"[A-Za-z0-9._-]+", identifier)
        ):
            raise CheckpointError("session-id 格式不正确")
        direct = directory / f"{identifier}.checkpoint.json"
        if direct.is_file():
            return direct
        matches = sorted(directory.glob(f"*{identifier}*.checkpoint.json"))
        if not matches:
            raise CheckpointError(f"找不到恢复点：{identifier}")
        if len(matches) > 1:
            raise CheckpointError("session-id 匹配多个恢复点，请提供完整日志 stem")
        return matches[0]
