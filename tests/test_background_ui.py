"""Unit tests for ijachi_router/background_ui.py."""

from __future__ import annotations

import time

import pytest

from ijachi_router.background_ui import BackgroundUIManager, BackgroundAgent


class FakeAgentResult:
    final_text = "Done!"


class FakeAgent:
    def run(self, task: str, max_steps: int = 10):
        time.sleep(0.05)
        return FakeAgentResult()


@pytest.fixture
def mgr():
    manager = BackgroundUIManager()
    yield manager
    manager.shutdown(wait=True)


def test_spawn_agent(mgr):
    aid = mgr.spawn_agent("Test agent", "do work", lambda: FakeAgent())
    assert aid in mgr.agents
    # Wait for completion
    bg = mgr.agents[aid]
    bg.future.result(timeout=5)
    time.sleep(0.05)
    assert bg.status == "done"
    assert bg.result_text == "Done!"


def test_active_count(mgr):
    aid = mgr.spawn_agent("Slow agent", "do work", lambda: FakeAgent())
    assert mgr.active_count() == 1
    bg = mgr.agents[aid]
    bg.future.result(timeout=5)
    time.sleep(0.05)
    assert mgr.active_count() == 0


def test_submit_task(mgr):
    def add():
        return 2 + 2

    tid = mgr.submit_task("add", add)
    bg = mgr.tasks[tid]
    assert bg.future.result(timeout=5) == 4
    time.sleep(0.05)
    assert bg.status == "done"


def test_expand_unknown(mgr, capsys):
    mgr.expand("no-such-id", accessible=True)
    captured = capsys.readouterr()
    assert "Unknown background work ID" in captured.out


def test_render_status_accessible(mgr, capsys):
    mgr.spawn_agent("Test agent", "do work", lambda: FakeAgent())
    mgr.render_status(accessible=True)
    captured = capsys.readouterr()
    assert "Test agent" in captured.out
