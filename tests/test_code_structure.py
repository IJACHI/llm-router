"""Unit tests for pure-Python code beautifiers (HTML, CSS, JSON, JS) and tool logging formatters."""

from __future__ import annotations

import pytest
from ijachi_router.formatter import CodeFormatter, _beautify_html, _beautify_css, _beautify_json
from ijachi_router.agent import _format_tool_call_summary


def test_html_beautifier_structures_document():
    raw_html = "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\"><title>Test</title><style>:root{--primary:#c0392b;}body{margin:0;padding:0;}</style></head><body><div class=\"container\"><h1>Hello</h1><p>Paragraph</p></div></body></html>"
    formatted = _beautify_html(raw_html)
    assert "<!DOCTYPE html>" in formatted
    assert "<head>" in formatted
    assert "  <meta charset=\"UTF-8\">" in formatted
    assert "--primary: #c0392b;" in formatted
    assert "<body>" in formatted
    assert "<div class=\"container\">" in formatted
    assert "<h1>Hello</h1>" in formatted
    assert formatted.endswith("\n")


def test_css_beautifier_formats_blocks_and_variables():
    raw_css = ":root { --primary: #c0392b; --accent: #f39c12; } * { margin: 0; padding: 0; } body { font-family: 'Poppins', sans-serif; line-height: 1.6; color: var(--dark); }"
    formatted = _beautify_css(raw_css)
    assert ":root {" in formatted
    assert "  --primary: #c0392b;" in formatted
    assert "  --accent: #f39c12;" in formatted
    assert "body {" in formatted
    assert "  font-family: 'Poppins', sans-serif;" in formatted
    assert "  line-height: 1.6;" in formatted


def test_json_beautifier():
    raw_json = '{"name":"ijachi","config":{"theme":"dark","priority":"speed"}}'
    formatted = _beautify_json(raw_json)
    assert '  "name": "ijachi"' in formatted
    assert '    "theme": "dark"' in formatted


def test_format_tool_call_summary_no_raw_dump():
    large_html = "<html>" + ("<div>content</div>\n" * 50) + "</html>"
    summary = _format_tool_call_summary("write_file", {"path": "index.html", "content": large_html})
    assert "index.html" in summary
    assert "lines" in summary
    assert "<div>" not in summary  # Large raw content is summarized, not dumped

    edit_summary = _format_tool_call_summary("edit_file", {"path": "app.py", "target_content": "a", "replacement_content": "b"})
    assert "app.py" in edit_summary

    cmd_summary = _format_tool_call_summary("run_command", {"command": "pytest -v"})
    assert "pytest -v" in cmd_summary


def test_code_formatter_format_content_dispatch():
    fmt = CodeFormatter(auto_format=True, require_comments=False)
    html_out = fmt.format_content("<html><head><title>Hi</title></head><body><h1>Hello</h1></body></html>", "index.html")
    assert "<title>Hi</title>" in html_out
    assert "\n" in html_out

    css_out = fmt.format_content("h1 { color: red; font-size: 20px; }", "styles.css")
    assert "  color: red;" in css_out
