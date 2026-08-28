"""验证 Agent checkpoint 的原子持久化、权限和查找。"""

import stat

import pytest

from patchpilot.checkpoint import (
    AgentState,
    CheckpointError,
    CheckpointStore,
)


def test_checkpoint_round_trip_and_permissions(tmp_path) -> None:
    directory = tmp_path / "sessions"
    path = directory / "20260828-demo.checkpoint.json"
    store = CheckpointStore(path, tmp_path / "workspace", False)
    state = AgentState(
        task="fix bug",
        context={"messages": [], "summary_lines": []},
        failed_calls={"fingerprint": [2, "error"]},
        evidence={"sequence": 1, "changes": [], "verifications": []},
    )

    store.save(state)
    loaded = store.load()

    assert loaded.workspace == str(tmp_path / "workspace")
    assert loaded.state.task == "fix bug"
    assert loaded.state.failed_calls["fingerprint"] == [2, "error"]
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_checkpoint_find_accepts_stem_or_short_id(tmp_path) -> None:
    path = tmp_path / "20260828-120000-abcd1234.checkpoint.json"
    path.write_text("{}", encoding="utf-8")

    assert CheckpointStore.find("20260828-120000-abcd1234", tmp_path) == path
    assert CheckpointStore.find("abcd1234", tmp_path) == path


def test_checkpoint_find_rejects_path_or_glob(tmp_path) -> None:
    with pytest.raises(CheckpointError, match="格式"):
        CheckpointStore.find("../secret", tmp_path)
    with pytest.raises(CheckpointError, match="格式"):
        CheckpointStore.find("*", tmp_path)


def test_checkpoint_remove_is_idempotent(tmp_path) -> None:
    path = tmp_path / "session.checkpoint.json"
    path.write_text("{}", encoding="utf-8")
    store = CheckpointStore(path, tmp_path, True)

    store.remove()
    store.remove()

    assert not path.exists()
