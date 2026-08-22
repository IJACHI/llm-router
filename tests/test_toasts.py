"""Unit tests for ijachi_router/toasts.py."""

import pytest

from ijachi_router.toasts import ToastManager, ToastLevel, toast_manager


@pytest.fixture
def fresh_toasts():
    t = ToastManager()
    t._reset()
    return t


def test_push_and_count(fresh_toasts):
    fresh_toasts.push("hello")
    fresh_toasts.push("world", level="success")
    assert fresh_toasts.pending_count == 2
    assert fresh_toasts.toasts[1].level == ToastLevel.SUCCESS


def test_pop_oldest(fresh_toasts):
    fresh_toasts.push("first")
    fresh_toasts.push("second")
    oldest = fresh_toasts.pop()
    assert oldest.message == "first"
    assert fresh_toasts.pending_count == 1


def test_badge_rendering(fresh_toasts):
    assert fresh_toasts.render_badge() == ""
    fresh_toasts.push("msg")
    assert "1 message" in fresh_toasts.render_badge()
    fresh_toasts.push("msg2")
    assert "2 messages" in fresh_toasts.render_badge()


def test_clear(fresh_toasts):
    fresh_toasts.push("a")
    fresh_toasts.push("b")
    fresh_toasts.clear()
    assert fresh_toasts.pending_count == 0


def test_module_singleton():
    from ijachi_router import toasts as toasts_mod

    a = toasts_mod.toast_manager
    b = toasts_mod.ToastManager()
    assert a is b
