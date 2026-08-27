"""Tests for agent efficiency, context compaction, think tag stripping, and security whitelist."""

import pytest
from pathlib import Path
from ijachi_router.agent import AgenticRouter, _strip_think_tags, _extract_tool_call, _extract_files_from_markdown
from ijachi_router.security import scan, scan_and_fix
from ijachi_router.providers.base import GenerationResult


def test_strip_think_tags_removes_reasoning_blocks():
    """Verify that <think>...</think> reasoning blocks from DeepSeek-R1 are stripped."""
    raw = """<think>
Here is my deep thought process:
1. The user wants a Flask app.
2. I should write config.py first.
</think>
```json
{
  "thought": "Writing config.py",
  "tool": "write_file",
  "args": {"path": "config.py", "content": "PORT = 5000"}
}
```"""
    cleaned = _strip_think_tags(raw)
    assert "<think>" not in cleaned
    assert "Writing config.py" in cleaned

    # Verify tool call extraction works seamlessly on think-tagged responses
    parsed = _extract_tool_call(raw)
    assert parsed is not None
    assert parsed["tool"] == "write_file"
    assert parsed["args"]["path"] == "config.py"


def test_strip_think_tags_with_markdown_files():
    """Verify markdown extraction works when model outputs think tags + files."""
    raw = """<thought>
Let's design the architecture.
</thought>
### File: `app.py`
```python
from flask import Flask
app = Flask(__name__)
```
"""
    extracted = _extract_files_from_markdown(raw)
    assert len(extracted) == 1
    assert extracted[0][0] == "app.py"
    assert "Flask" in extracted[0][1]


def test_security_scanner_whitelists_dev_boilerplate():
    """Verify standard development secret boilerplate does not trigger false positive HIGH alerts."""
    code = """
import os
SECRET_KEY = os.environ.get("SECRET_KEY", "your-secret-key-here")
DEV_KEY = "dev-secret"
PASSWORD = "admin123"
"""
    report = scan(code)
    assert report.is_safe is True
    assert len(report.issues) == 0


def test_security_scanner_still_flags_real_hardcoded_secrets():
    """Verify real hardcoded API keys are still detected by security scan."""
    code = 'API_KEY = "sk-live-9876543210abcdef9876543210abcdef"'
    report = scan(code)
    assert report.is_safe is False
    categories = {i.category for i in report.issues}
    assert "Secrets Exposure" in categories


def test_agent_context_compaction_prevents_token_ballooning(monkeypatch, tmp_path):
    """Verify that multi-step agent execution compacts prompt history and avoids token bloat."""
    agent = AgenticRouter(root_dir=tmp_path, require_approval=False, memory_dir=tmp_path / "mem")

    prompts_received = []

    def mock_route(prompt, **kwargs):
        prompts_received.append(prompt)
        step_num = len(prompts_received)
        if step_num < 5:
            # Generate a 1,000 char file on each step
            file_content = f"# File {step_num}\n" + ("x = 1\n" * 100)
            return GenerationResult(
                text=f'```json\n{{"thought": "step {step_num}", "tool": "write_file", "args": {{"path": "file_{step_num}.py", "content": "{file_content}"}}}}\n```',
                model="gpt-4o",
                provider="openai",
                cost_usd=0.0001,
                latency_s=0.05,
                input_tokens=100,
                output_tokens=50,
            )
        else:
            return GenerationResult(
                text='```json\n{"thought": "done", "final_answer": "All 5 files created successfully."}\n```',
                model="gpt-4o",
                provider="openai",
                cost_usd=0.0001,
                latency_s=0.05,
                input_tokens=100,
                output_tokens=20,
            )

    monkeypatch.setattr("ijachi_router.agent.route", mock_route)

    result = agent.run("Build a 5-file project", max_steps=6)
    assert result.completed is True
    assert len(prompts_received) == 5

    # Check that the 5th prompt is bounded and does not contain all 5,000 raw uncompacted lines
    last_prompt = prompts_received[-1]
    assert len(last_prompt) < 15000  # Stays compact
    assert "Completed Earlier Steps:" in last_prompt or "Execution Progress:" in last_prompt


def test_auto_approve_persistence_across_multiple_writes(tmp_path):
    """Verify auto_approve_task=True writes all files without user prompts."""
    agent = AgenticRouter(root_dir=tmp_path, require_approval=True, memory_dir=tmp_path / "mem", permission_mode="auto")
    assert agent.tools.auto_approve_task is False

    # Simulate run start
    if agent.permission_mode in ("accept-edits", "auto"):
        agent.tools.auto_approve_task = True

    # Writes 3 files consecutively
    res1 = agent.tools.write_file("a.py", "print('a')", require_approval=True)
    res2 = agent.tools.write_file("b.py", "print('b')", require_approval=True)
    res3 = agent.tools.write_file("c.py", "print('c')", require_approval=True)

    assert "Successfully wrote" in res1
    assert "Successfully wrote" in res2
    assert "Successfully wrote" in res3
    assert (tmp_path / "a.py").exists()
    assert (tmp_path / "b.py").exists()
    assert (tmp_path / "c.py").exists()
