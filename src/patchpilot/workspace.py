"""
文件名：workspace.py

功能：
管理 Agent 可访问的工作区，阻止路径逃逸和敏感文件访问。
"""

from pathlib import Path


BLOCKED_DIRECTORIES = {".git", ".ssh", ".aws", ".gnupg"}
BLOCKED_FILENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.test",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials.json",
    "secrets.json",
}
BLOCKED_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}


class WorkspaceViolation(Exception):
    """工作区访问违规。"""


class SensitivePathViolation(WorkspaceViolation):
    """Agent 尝试访问敏感文件或目录。"""


class Workspace:
    """受约束的项目工作区。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        if not self.root.exists():
            raise ValueError(f"工作区不存在：{self.root}")
        if not self.root.is_dir():
            raise ValueError(f"工作区不是目录：{self.root}")

    def resolve(
        self,
        user_path: str,
        *,
        allow_sensitive: bool = False,
    ) -> Path:
        """解析路径，并检查绝对路径、目录穿越、符号链接和敏感内容。"""

        if not isinstance(user_path, str):
            raise WorkspaceViolation("路径必须是字符串")

        # 模型经常用空字符串表示当前目录，因此统一规范为工作区根目录。
        normalised = user_path.strip() or "."
        candidate = Path(normalised).expanduser()
        if candidate.is_absolute():
            raise WorkspaceViolation(f"不允许使用绝对路径：{user_path}")

        target = (self.root / candidate).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as error:
            raise WorkspaceViolation(
                f"拒绝访问工作区外部路径：{user_path}"
            ) from error

        if not allow_sensitive:
            self.ensure_not_sensitive(target)
        return target

    def ensure_not_sensitive(self, target: Path) -> None:
        """拒绝敏感目录、凭据文件、私钥和证书。"""

        try:
            relative = target.resolve().relative_to(self.root)
        except ValueError as error:
            raise WorkspaceViolation(f"路径不在工作区内：{target}") from error

        # 必须先检查父目录，不能让 .git/.env.example 因模板例外而通过。
        for part in relative.parts[:-1]:
            if part.lower() in BLOCKED_DIRECTORIES:
                raise SensitivePathViolation(f"拒绝访问敏感目录：{part}")

        name = relative.name.lower()
        if name in BLOCKED_DIRECTORIES:
            raise SensitivePathViolation(f"拒绝访问敏感目录：{relative}")
        if name == ".env.example":
            return
        if name in BLOCKED_FILENAMES:
            raise SensitivePathViolation(f"拒绝访问敏感文件：{relative}")
        if name.startswith(".env."):
            raise SensitivePathViolation(f"拒绝访问敏感环境配置：{relative}")
        if target.suffix.lower() in BLOCKED_SUFFIXES:
            raise SensitivePathViolation(f"拒绝访问密钥或证书文件：{relative}")

    def is_sensitive(self, target: Path) -> bool:
        """判断目录列表是否应隐藏目标；逃逸符号链接同样隐藏。"""

        try:
            self.ensure_not_sensitive(target)
        except WorkspaceViolation:
            return True
        return False
