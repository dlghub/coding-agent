"""
文件名：test_security.py

功能：
验证敏感路径、空路径和目录列表的安全行为。
"""

from pathlib import Path

import pytest

from patchpilot.tools.files import ListFilesTool, ReadFileTool
from patchpilot.workspace import SensitivePathViolation, Workspace


def test_list_files_treats_empty_path_as_root(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('ok')\n", encoding="utf-8")
    output = ListFilesTool(Workspace(tmp_path)).execute({"path": ""})
    assert "app.py" in output


def test_list_files_hides_secrets_but_keeps_example(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=value\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("SECRET=\n", encoding="utf-8")
    (tmp_path / "private.pem").write_text("secret\n", encoding="utf-8")
    output = ListFilesTool(Workspace(tmp_path)).execute({})
    assert ".env\n" not in output
    assert "private.pem" not in output
    assert ".env.example" in output


@pytest.mark.parametrize(
    "path",
    [".env", ".env.local", ".git/config", "private.pem", "server.key", "credentials.json"],
)
def test_read_file_rejects_sensitive_paths(tmp_path: Path, path: str) -> None:
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("secret", encoding="utf-8")
    with pytest.raises(SensitivePathViolation):
        ReadFileTool(Workspace(tmp_path)).execute({"path": path})


def test_read_file_allows_env_example(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("AGENT_API_KEY=\n", encoding="utf-8")
    output = ReadFileTool(Workspace(tmp_path)).execute({"path": ".env.example"})
    assert "AGENT_API_KEY=" in output


def test_list_files_hides_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    link = tmp_path / "outside"
    try:
        link.symlink_to(outside, target_is_directory=True)
        output = ListFilesTool(Workspace(tmp_path)).execute({})
        assert "outside" not in output
    finally:
        link.unlink(missing_ok=True)
        outside.rmdir()
