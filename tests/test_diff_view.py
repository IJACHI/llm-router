"""Unit tests for ijachi_router/diff_view.py."""

from __future__ import annotations

from rich.panel import Panel
from rich.text import Text

from ijachi_router.diff_view import DiffRenderer, InlineDiff


def test_unified_diff_lines():
    old = "line1\nline2\nline3\n"
    new = "line1\nline2 changed\nline3\n"
    renderer = DiffRenderer()
    lines = renderer.unified_diff_lines(old, new, "test.txt")
    assert any(line.startswith("--- a/test.txt") for line in lines)
    assert any(line.startswith("+++ b/test.txt") for line in lines)
    assert any(line.startswith("-line2") for line in lines)
    assert any(line.startswith("+line2 changed") for line in lines)


def test_render_returns_panel():
    renderer = DiffRenderer()
    renderable = renderer.render("a\nb\n", "a\nc\n", "file.py")
    assert isinstance(renderable, Panel)


def test_render_accessible_returns_string():
    renderer = DiffRenderer(accessible=True)
    renderable = renderer.render("a\nb\n", "a\nc\n", "file.py")
    assert isinstance(renderable, str)
    assert "--- a/file.py" in renderable


def test_summarize():
    renderer = DiffRenderer()
    summary = renderer._summarize("a\nb\nc\n", "a\nb\nc\nd\n")
    assert "Added 1 line(s)" in summary
    assert "removed 0 line(s)" in summary


def test_inline_diff(capsys):
    diff = InlineDiff()
    diff.print("old value", "new value", "My change")
    captured = capsys.readouterr()
    assert "My change" in captured.out
    assert "old value" in captured.out
    assert "new value" in captured.out
