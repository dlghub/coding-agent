"""验证最终 Git 工作树审查。"""

import subprocess

from patchpilot.git_review import GitInspector


def test_git_review_skips_non_repository(tmp_path) -> None:
    review = GitInspector(tmp_path).inspect()

    assert review.available is False
    assert review.diff_check_passed is None


def test_git_review_collects_status_stat_and_diff_check(tmp_path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    tracked = tmp_path / "app.py"
    tracked.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    tracked.write_text("VALUE = 2  \n", encoding="utf-8")
    (tmp_path / "new.py").write_text("NEW = True\n", encoding="utf-8")

    review = GitInspector(tmp_path).inspect()

    assert review.available is True
    assert any("app.py" in line for line in review.status_lines)
    assert any("new.py" in line for line in review.status_lines)
    assert "app.py" in review.diff_stat
    assert review.diff_check_passed is False


def test_git_review_reports_clean_repository(tmp_path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    review = GitInspector(tmp_path).inspect()

    assert review.available is True
    assert review.status_lines == []
    assert review.diff_stat == ""
    assert review.diff_check_passed is True
