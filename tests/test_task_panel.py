"""Unit tests for ijachi_router/task_panel.py."""

from __future__ import annotations

import time

from rich.panel import Panel

from ijachi_router.task_panel import TaskPanel, TaskStatus


def test_add_and_status():
    panel = TaskPanel()
    idx = panel.add("read file")
    assert panel.items[idx].status == TaskStatus.PENDING


def test_set_active_and_complete():
    panel = TaskPanel()
    idx = panel.add("fix bug")
    panel.set_active(idx)
    assert panel.items[idx].status == TaskStatus.ACTIVE
    time.sleep(0.01)
    panel.complete(idx)
    assert panel.items[idx].status == TaskStatus.COMPLETED
    assert panel.items[idx].duration >= 0


def test_render_returns_panel():
    panel = TaskPanel()
    panel.add("a")
    panel.add("b")
    panel.set_active(0)
    renderable = panel.render()
    assert isinstance(renderable, Panel)


def test_token_formatting():
    panel = TaskPanel()
    assert panel._format_tokens(999) == "999"
    assert panel._format_tokens(1500) == "1.5k"
    assert panel._format_tokens(2_000_000) == "2.0M"


def test_completed_items_collapse():
    panel = TaskPanel(max_visible_completed=2)
    for i in range(4):
        panel.add(f"task {i}")
        panel.complete(i)
    renderable = panel.render()
    text = str(renderable.renderable)
    assert ".. +2 completed" in text


def test_accessible_output(capsys):
    panel = TaskPanel(accessible=True)
    panel.add("job 1")
    panel.set_active(0)
    panel.complete(0)
    captured = capsys.readouterr()
    assert "tasks:" in captured.out
    assert "[x] job 1" in captured.out
