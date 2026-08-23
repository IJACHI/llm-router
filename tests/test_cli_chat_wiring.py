"""Tests for CLI chat UI wiring and renderer integration."""

from __future__ import annotations

from ijachi_router.ui import (
    set_theme,
    get_current_theme,
    list_themes,
    ChatMessageRenderer,
    get_welcome_card,
    get_permission_mode_label,
    cycle_permission_mode,
)
from ijachi_router.transcript import ToolCall


def test_theme_switching():
    """set_theme changes the active global theme and returns resolved name."""
    original = get_current_theme()
    try:
        assert set_theme("coral") == "coral"
        assert get_current_theme() == "coral"

        assert set_theme("accessible") == "accessible"
        assert get_current_theme() == "accessible"
    finally:
        set_theme(original)


def test_list_themes_includes_known_themes():
    """list_themes exposes all shipped themes plus auto."""
    themes = list_themes()
    for name in ("dark", "light", "ansi", "accessible", "claude", "auto"):
        assert name in themes


def test_welcome_card_renders():
    """get_welcome_card returns a double-bordered panel with key metadata."""
    from ijachi_router.ui import _console

    panel = get_welcome_card(model="gpt-4o", billing="API Usage Billing", workspace="/tmp")
    title = panel.title or ""
    assert "ijachi-code" in title
    with _console.capture() as capture:
        _console.print(panel)
    text = capture.get()
    assert "gpt-4o" in text
    assert "API Usage Billing" in text


def test_permission_mode_helpers():
    """Permission mode label and cycling helpers work."""
    assert "manual" in get_permission_mode_label("manual")
    assert "auto" in get_permission_mode_label("auto")
    assert cycle_permission_mode("manual") == "accept-edits"
    assert cycle_permission_mode("auto") == "manual"


def test_chat_renderer_user_prompt():
    """render_user_prompt returns a panel (or plain text) containing the prompt."""
    renderer = ChatMessageRenderer(accessible=False)
    result = renderer.render_user_prompt("hello world", telemetry_summary="Thought for 2s")
    content = result.renderable.plain
    assert "hello world" in content
    assert "Thought for 2s" in content
    assert "you" in result.title


def test_chat_renderer_user_prompt_accessible():
    """render_user_prompt in accessible mode returns labeled plain text."""
    renderer = ChatMessageRenderer(accessible=True)
    result = renderer.render_user_prompt("hello")
    assert "you: hello" in result


def test_chat_renderer_assistant_response():
    """render_assistant_response includes model, provider, cost, and text."""
    renderer = ChatMessageRenderer(accessible=False)
    result = renderer.render_assistant_response(
        "Done!",
        model="claude-3-5-sonnet",
        provider="anthropic",
        cost_usd=0.005,
        telemetry_summary="read 2 files",
    )
    content = result.renderable.plain
    title = result.title
    assert "Done!" in content
    assert "claude-3-5-sonnet" in title
    assert "anthropic" in title
    assert "$0.0050" in title
    assert "read 2 files" in content


def test_chat_renderer_tool_calls():
    """render_tool_calls returns a panel listing tool names and argument keys."""
    renderer = ChatMessageRenderer(accessible=False)
    tool_calls = [
        {"tool_name": "read_file", "args": {"path": "core.py"}, "output": "..."},
        {"tool_name": "edit_file", "args": {"path": "ui.py", "old": "a", "new": "b"}, "output": "ok"},
    ]
    result = renderer.render_tool_calls(tool_calls)
    plain = result.renderable.plain
    assert "read_file" in plain
    assert "edit_file" in plain
    assert "path" in plain


def test_tool_call_object_for_transcript():
    """ToolCall objects can be created with tool_name, args, and output."""
    tc = ToolCall(tool_name="list_dir", args={"path": "."}, output="files")
    assert tc.tool_name == "list_dir"
    assert tc.args == {"path": "."}
    assert tc.output == "files"
