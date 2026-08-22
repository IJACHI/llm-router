"""Tests for the unified diff renderer."""

from __future__ import annotations

from ijachi_router.diff_view import DiffRenderer, InlineDiff, render_edit_approval


def test_unified_diff_lines():
    """unified_diff_lines returns the expected diff format."""
    renderer = DiffRenderer()
    old = "line one\nline two\nline three"
    new = "line one\nline two changed\nline three"
    lines = renderer.unified_diff_lines(old, new, "file.txt")
    joined = "\n".join(lines)
    assert "--- a/file.txt" in joined
    assert "+++ b/file.txt" in joined
    assert "-line two" in joined
    assert "+line two changed" in joined


def test_render_returns_panel():
    """render returns a Rich Panel with colored diff content."""
    renderer = DiffRenderer(accessible=False)
    panel = renderer.render("a\nb\nc", "a\nB\nc", "config.py")
    text = panel.renderable
    plain = text.plain
    assert "config.py" in panel.title
    assert "-b" in plain
    assert "+B" in plain


def test_render_accessible_mode():
    """In accessible mode render returns a plain string."""
    renderer = DiffRenderer(accessible=True)
    result = renderer.render("x", "X", "x.txt")
    assert isinstance(result, str)
    assert "-x" in result
    assert "+X" in result


def test_summarize_counts():
    """_summarize reports added/removed line counts."""
    renderer = DiffRenderer()
    assert renderer._summarize("a\nb", "a\nb\nc") == "Added 1 line(s), removed 0 line(s)"
    assert renderer._summarize("a\nb\nc", "a") == "Added 0 line(s), removed 2 line(s)"


def test_inline_diff(capsys):
    """InlineDiff prints old/new lines with level styles."""
    diff = InlineDiff(accessible=False)
    diff.print("old value", "new value", label="Value")
    captured = capsys.readouterr()
    assert "Value" in captured.out
    assert "- old value" in captured.out
    assert "+ new value" in captured.out


def test_render_edit_approval_smoke():
    """render_edit_approval runs without raising."""
    render_edit_approval("x", "X", "test.py", accessible=True)
