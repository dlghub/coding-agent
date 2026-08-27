"""
文件名: workspace.py

功能：
管理 Agent 可以访问的工作区，并阻止路径逃逸。

安全边界：
所有文件工具都必须通过 Workspace.resolve() 获取真实路径，
不能直接将模型提供的路径传给 open()、Path.read_text() 等函数。
"""

from pathlib import Path



class WorkspaceViolation(Exception):
    """工作区访问违规异常"""
    pass


class Workspace:
    """受约束的项目工作区"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

        if not self.root.exists():
            raise ValueError(f"工作区根目录不存在: {self.root}")

        if not self.root.is_dir():
            raise ValueError(f"工作区根目录不是文件夹: {self.root}")

    def resolve(self, user_path: str) -> Path:
        """将模型提供的相对路径解析为工作区内的真实路径"""

        if not user_path.strip():
            raise WorkspaceViolation("路径不能为空")

        candidate = Path(user_path).expanduser()

        # 不允许模型直接提交绝对路径
        if candidate.is_absolute():
            raise WorkspaceViolation(f"不允许使用绝对路径: {candidate}")

        target = (self.root / candidate).resolve()

        try:
            target.relative_to(self.root)
        except ValueError as error:
            raise WorkspaceViolation(
                f"拒绝访问工作区外部路径: {user_path}"
            ) from error

        return target