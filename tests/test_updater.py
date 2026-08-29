"""Unit tests for Auto-Updater Engine."""

from __future__ import annotations

from unittest.mock import patch


def test_update_already_up_to_date(tmp_path):
    """When origin/main has no new commits, should return 'Already up to date'."""
    # Make tmp_path look like a git repo
    (tmp_path / ".git").mkdir()

    with patch("ijachi_router.updater._run") as mock_run, \
         patch("ijachi_router.updater.Path.home", return_value=tmp_path):

        # fetch succeeds, rev-list returns 0 (no new commits)
        mock_run.side_effect = [
            (0, "", ""),        # git fetch
            (0, "0", ""),       # git rev-list count → 0 new commits
        ]

        from ijachi_router.updater import update_ijachi
        msg = update_ijachi()

    assert "up to date" in msg.lower()


def test_update_success(tmp_path):
    """When new commits exist, should fetch, reset, reinstall, and return success."""
    (tmp_path / ".git").mkdir()

    with patch("ijachi_router.updater._run") as mock_run, \
         patch("ijachi_router.updater.Path.home", return_value=tmp_path):

        mock_run.side_effect = [
            (0, "", ""),        # git fetch
            (0, "3", ""),       # git rev-list → 3 new commits
            (0, "HEAD is now at abc1234", ""),  # git reset --hard
            (0, "", ""),        # pip install (venv pip not found → skipped via path check)
        ]

        from ijachi_router.updater import update_ijachi
        msg = update_ijachi()

    assert "successfully updated" in msg.lower()


def test_update_fetch_failure(tmp_path):
    """When git fetch fails, should surface a meaningful error message."""
    (tmp_path / ".git").mkdir()

    with patch("ijachi_router.updater._run") as mock_run, \
         patch("ijachi_router.updater.Path.home", return_value=tmp_path):

        mock_run.side_effect = [
            (1, "", "fatal: unable to access remote"),  # git fetch fails
        ]

        from ijachi_router.updater import update_ijachi
        msg = update_ijachi()

    assert "fetch failed" in msg.lower() or "error" in msg.lower() or "unable" in msg.lower()


def test_update_returns_string():
    """update_ijachi must always return a non-empty string."""
    with patch("ijachi_router.updater._run", return_value=(0, "0", "")):
        from ijachi_router.updater import update_ijachi
        result = update_ijachi()
    assert isinstance(result, str)
    assert len(result) > 0
