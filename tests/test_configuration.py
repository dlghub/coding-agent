"""
文件名：test_configuration.py

功能：
验证外置配置路径和完整模式的凭据隔离约束。
"""

from pathlib import Path

import pytest

from patchpilot.cli import (
    configuration_path,
    ensure_config_outside_writable_workspace,
)
from patchpilot.config import ConfigurationError, Settings
from patchpilot.workspace import Workspace


def test_default_configuration_path_is_outside_project(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PATCHPILOT_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert configuration_path() == (tmp_path / ".config" / "patchpilot" / ".env")


def test_explicit_configuration_path(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "custom.env"
    monkeypatch.setenv("PATCHPILOT_CONFIG", str(path))
    assert configuration_path() == path.resolve()


def test_full_mode_rejects_config_inside_workspace(tmp_path: Path) -> None:
    config = tmp_path / ".config" / "patchpilot" / ".env"
    config.parent.mkdir(parents=True)
    config.write_text("AGENT_API_KEY=secret\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="工作区外部"):
        ensure_config_outside_writable_workspace(config, Workspace(tmp_path), False)


def test_read_only_mode_allows_broad_workspace(tmp_path: Path) -> None:
    config = tmp_path / ".config" / "patchpilot" / ".env"
    config.parent.mkdir(parents=True)
    config.write_text("AGENT_API_KEY=secret\n", encoding="utf-8")
    ensure_config_outside_writable_workspace(config, Workspace(tmp_path), True)


def test_settings_reads_context_budget(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_API_KEY", "secret")
    monkeypatch.setenv("AGENT_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("AGENT_MODEL", "test-model")
    monkeypatch.setenv("AGENT_MAX_CONTEXT_CHARS", "64000")

    assert Settings.from_env().max_context_chars == 64_000


def test_settings_rejects_too_small_context_budget(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_API_KEY", "secret")
    monkeypatch.setenv("AGENT_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("AGENT_MODEL", "test-model")
    monkeypatch.setenv("AGENT_MAX_CONTEXT_CHARS", "9999")

    with pytest.raises(ConfigurationError, match="至少为 10000"):
        Settings.from_env()
