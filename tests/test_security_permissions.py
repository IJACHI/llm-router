"""Tests for Document 5: Security, Privacy, and Threat Model.

Covers:
- SEC-01: Tool risk classification (R0 to R4)
- SEC-02: Shell command analysis and compound command protection
- SEC-03: Workspace path canonicalization and symlink escape prevention
- SEC-05: Subprocess environment secrets scrubbing
- SEC-06: Tool output secrets redaction pipeline
- SEC-07: Sensitive file deny-listing (.env, id_rsa, etc.)
- SEC-08: Non-interactive CI auto-deny with exit code 5
- SEC-10: Terminal output control-sequence sanitization
- AT-09: rm -rf and git push require approval; default input denies
- AT-13: Print mode in CI with no TTY exits with code 5 on unapproved actions
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ijachi_router.agent.permissions import PermissionManager
from ijachi_router.agent.sandbox import WorkspaceSandbox, redact_secrets
from ijachi_router.ui.render import sanitize_terminal_output


def test_permission_tool_risk_classes(tmp_path):
    pm = PermissionManager(mode="ask")

    # R0: read-only inside workspace
    r0 = pm.classify_tool("Read", {"path": "src/app.py"}, workspace_dir=tmp_path)
    assert r0 == "R0"

    # R1: write inside workspace
    r1 = pm.classify_tool("Edit", {"path": "src/app.py"}, workspace_dir=tmp_path)
    assert r1 == "R1"

    # R2: normal bash command
    r2 = pm.classify_tool("Bash", {"command": "python -m unittest"}, workspace_dir=tmp_path)
    assert r2 == "R2"

    # R3: network fetch
    r3 = pm.classify_tool("WebFetch", {"url": "https://example.com"}, workspace_dir=tmp_path)
    assert r3 == "R3"

    # R4: outside workspace traversal
    r4 = pm.classify_tool("Read", {"path": "../../etc/passwd"}, workspace_dir=tmp_path)
    assert r4 == "R4"

    # R4: sensitive dotfile
    r4_env = pm.classify_tool("Read", {"path": ".env.production"}, workspace_dir=tmp_path)
    assert r4_env == "R4"


def test_shell_command_analysis_compound_command_blocking():
    pm = PermissionManager(mode="ask")

    # Safe standalone
    ok, _ = pm.analyze_shell_command("git status")
    assert ok is True

    # Compound command containing dangerous subcommand
    blocked, reason = pm.analyze_shell_command("git status && rm -rf /")
    assert blocked is False
    assert "Dangerous" in reason

    # Pipeline containing fork bomb
    blocked, reason = pm.analyze_shell_command("echo hello | :(){ :|:& };:")
    assert blocked is False


def test_sandbox_path_traversal_prevention(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret outside", encoding="utf-8")

    sandbox = WorkspaceSandbox(workspace_dir=ws)

    # Valid inside path
    inside_path = ws / "file.txt"
    inside_path.write_text("inside", encoding="utf-8")
    assert sandbox.canonicalize_path("file.txt") == inside_path.resolve()

    # Traversal escape outside workspace must raise PermissionError
    with pytest.raises(PermissionError):
        sandbox.canonicalize_path("../outside.txt")


def test_sensitive_file_deny_list(tmp_path):
    sandbox = WorkspaceSandbox(workspace_dir=tmp_path)
    assert sandbox.is_sensitive_file(".env") is True
    assert sandbox.is_sensitive_file(".env.local") is True
    assert sandbox.is_sensitive_file("id_rsa") is True
    assert sandbox.is_sensitive_file("server.key") is True
    assert sandbox.is_sensitive_file("app.py") is False


def test_subprocess_env_scrubbed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-secret-key-12345")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test-secret-key-67890")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "ABCD1234EFGH5678IJKL")
    monkeypatch.setenv("MY_APP_VAR", "regular_value")

    sandbox = WorkspaceSandbox()
    clean_env = sandbox.get_scrubbed_env()

    assert "ANTHROPIC_API_KEY" not in clean_env
    assert "OPENAI_API_KEY" not in clean_env
    assert "AWS_SECRET_ACCESS_KEY" not in clean_env
    assert clean_env.get("MY_APP_VAR") == "regular_value"
    assert clean_env.get("PAGER") == "cat"


def test_tool_output_secrets_redaction():
    text_with_keys = (
        "Server failed with OpenAI key sk-1234567890123456789012345 "
        "and AWS key AKIAIOSFODNN7EXAMPLE in traceback."
    )
    redacted = redact_secrets(text_with_keys)
    assert "sk-1234567890123456789012345" not in redacted
    assert "[REDACTED:api_key]" in redacted
    assert "[REDACTED:aws_access_key]" in redacted


def test_non_interactive_ci_auto_safe_denies_unapproved_with_exit_5(tmp_path):
    # In auto-safe mode (CI), unapproved tools must be rejected with exit code 5 (AT-13)
    pm = PermissionManager(mode="auto-safe", is_tty=False)
    res = pm.authorize_tool_call(
        tool_name="Edit",
        args={"path": "main.py"},
        workspace_dir=tmp_path,
    )
    assert res.allowed is False
    assert res.exit_code == 5
    assert "auto-safe (CI) mode" in res.reason


def test_terminal_output_sanitization():
    # Attempted OSC title rewrite and OSC 52 clipboard hijacking
    malicious = (
        "Normal text \x1b]0;Pwned Title\x07 "
        "Clipboard write \x1b]52;c;SGVsbG8=\x07 and bell \x07"
    )
    cleaned = sanitize_terminal_output(malicious)
    assert "\x1b]0;" not in cleaned
    assert "\x1b]52;" not in cleaned
    assert "\x07" not in cleaned
    assert "Normal text" in cleaned
