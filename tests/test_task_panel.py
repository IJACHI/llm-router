"""Tests for the live task checklist panel."""

from __future__ import annotations

from ijachi_router.task_panel import TaskPanel, TaskStatus


def test_add_and_complete_task():
    """Tasks can be added, activated, and completed."""
    panel = TaskPanel(accessible=True)
    idx = panel.add("Read core.py")
    assert panel.items[idx].status == TaskStatus.PENDING

    panel.set_active(idx)
    assert panel.items[idx].status == TaskStatus.ACTIVE
    assert panel.items[idx].start_time is not None

    panel.complete(idx, "done")
    assert panel.items[idx].status == TaskStatus.COMPLETED
    assert panel.items[idx].finish_time is not None
    assert panel.items[idx].metadata == "done"


def test_task_completion_hides_old_items():
    """Only the configured number of completed tasks remain visible."""
    panel = TaskPanel(accessible=False, max_visible_completed=2)
    for i in range(5):
        panel.add(f"Task {i}")
        panel.complete(i)

    renderable = panel.render()
    text = renderable.renderable  # Panel body is a Text object
    content = text.plain
    assert content.count("Task") == 2
    assert "+3 completed" in content


def test_tokens_and_state():
    """Token counters and state label propagate to the rendered header."""
    panel = TaskPanel(accessible=True)
    panel.add("Work")
    panel.set_tokens(1500, 500)
    panel.set_state("running")

    header = panel.render().title
    assert "2.0k tokens" in header
    assert "running" in header


def test_format_helpers():
    """Duration and token helpers format values nicely."""
    assert TaskPanel._format_duration(45) == "45s"
    assert TaskPanel._format_duration(125) == "2m 5s"
    assert TaskPanel._format_duration(3665) == "1h 1m 5s"

    assert TaskPanel._format_tokens(950) == "950"
    assert TaskPanel._format_tokens(1_500) == "1.5k"
    assert TaskPanel._format_tokens(2_500_000) == "2.5M"
