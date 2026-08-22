"""Tests for the toast notification manager."""

from __future__ import annotations

from ijachi_router.toasts import ToastManager, ToastLevel, toast_manager


def test_toast_singleton():
    """The module-level toast_manager is a singleton."""
    a = ToastManager()
    b = ToastManager()
    assert a is b
    assert toast_manager is a


def test_push_and_pop():
    """Toasts can be pushed, popped FIFO, and cleared."""
    mgr = ToastManager()
    mgr._reset()

    t1 = mgr.push("First", level="info")
    t2 = mgr.push("Second", level="success")
    assert mgr.pending_count == 2
    assert t1.level == ToastLevel.INFO
    assert t2.level == ToastLevel.SUCCESS

    popped = mgr.pop()
    assert popped is t1
    assert mgr.pending_count == 1

    mgr.clear()
    assert mgr.pending_count == 0
    assert mgr.pop() is None


def test_render_badge():
    """render_badge returns a short Rich markup string only when pending."""
    mgr = ToastManager()
    mgr._reset()
    assert mgr.render_badge() == ""

    mgr.push("hello")
    badge = mgr.render_badge()
    assert "1 message" in badge
    assert "click" in badge

    mgr.push("again")
    assert "2 messages" in mgr.render_badge()


def test_print_pending(capsys):
    """print_pending renders pending toasts and clears the queue."""
    mgr = ToastManager()
    mgr._reset()
    mgr.push("Done", level="success")
    mgr.print_pending()

    captured = capsys.readouterr()
    assert "Done" in captured.out
    assert mgr.pending_count == 0


def test_toast_metadata():
    """Extra keyword args are stored in toast metadata."""
    mgr = ToastManager()
    mgr._reset()
    toast = mgr.push("event", level="warning", task_id="123")
    assert toast.metadata == {"task_id": "123"}
