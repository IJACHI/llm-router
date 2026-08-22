"""Tests for the background subagent/task UI manager."""

from __future__ import annotations

import time

import pytest

from ijachi_router.background_ui import BackgroundUIManager


@pytest.fixture
def manager():
    """Return a fresh manager and shut down its executor after each test."""
    mgr = BackgroundUIManager(max_workers=4)
    yield mgr
    mgr.shutdown(wait=True)


def test_submit_task_completes(manager):
    """A submitted callable runs in the background and stores its result."""
    task_id = manager.submit_task("double", lambda x: x * 2, 21)
    bg = manager.get(task_id)
    assert bg is not None
    assert bg.name == "double"

    # Wait for completion
    bg.future.result(timeout=5)
    time.sleep(0.1)

    assert bg.status == "done"
    assert bg.result_text == "42"


def test_submit_task_error(manager):
    """A failing background task records an error status."""
    task_id = manager.submit_task("fail", lambda: 1 / 0)
    bg = manager.get(task_id)

    with pytest.raises(Exception):
        bg.future.result(timeout=5)
    time.sleep(0.1)

    assert bg.status == "error"
    assert "division" in bg.error or "zero" in bg.error.lower()


def test_active_count_tracks_running_and_done(manager):
    """active_count returns only still-running work."""
    started = {"n": 0}
    done = {"n": 0}

    def slow():
        started["n"] += 1
        time.sleep(0.2)
        done["n"] += 1
        return "ok"

    tid1 = manager.submit_task("slow1", slow)
    tid2 = manager.submit_task("slow2", slow)

    # Wait until both have started
    timeout = time.monotonic() + 5
    while started["n"] < 2 and time.monotonic() < timeout:
        time.sleep(0.05)

    assert manager.active_count() == 2
    assert len(manager.list_active()) == 2

    # Wait for completion
    for tid in (tid1, tid2):
        manager.get(tid).future.result(timeout=5)
    time.sleep(0.1)

    assert manager.active_count() == 0


def test_format_duration():
    """Duration helper formats seconds nicely."""
    assert BackgroundUIManager._format_duration(30) == "30s"
    assert BackgroundUIManager._format_duration(90) == "1m 30s"
    assert BackgroundUIManager._format_duration(3600) == "1h 0m 0s"
