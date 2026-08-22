"""Unit tests for agent robustness, JSON tool parsing, multi-strategy repair, and batch approvals."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ijachi_router.agent import (
    AgenticRouter,
    WorkspaceTools,
    _extract_balanced_json,
    _try_parse_json,
    _extract_tool_call,
)
from ijachi_router.context_manager import ContextManager
from ijachi_router.providers.base import GenerationResult


# ---------------------------------------------------------------------------
# JSON Extraction & Repair Tests
# ---------------------------------------------------------------------------

def test_extract_balanced_json_with_nested_braces():
    """Test extracting JSON when python code in arguments contains nested dictionary literals."""
    raw = """
    Here is the tool call:
    ```json
    {
        "thought": "Writing user config dictionary",
        "tool": "write_file",
        "args": {
            "path": "config.py",
            "content": "CONFIG = {'db': {'host': 'localhost', 'port': 5432}}"
        }
    }
    ```
    """
    balanced = _extract_balanced_json(raw)
    assert balanced is not None
    data = json.loads(balanced)
    assert data["tool"] == "write_file"
    assert "CONFIG = {'db':" in data["args"]["content"]


def test_extract_tool_call_with_stray_prefix_and_markdown():
    """Test extracting tool call when model outputs conversational text before json block."""
    raw = """y

```json
{
  "thought": "Creating summarization module",
  "tool": "write_file",
  "args": {
    "path": "summarization.py",
    "content": "def summarize(text): return text[:100]"
  }
}
```
"""
    data = _extract_tool_call(raw)
    assert data is not None
    assert data["tool"] == "write_file"
    assert data["args"]["path"] == "summarization.py"


def test_extract_tool_call_with_raw_newlines_in_json():
    """Test repair when JSON has literal unescaped newlines in content string."""
    raw = """{
  "thought": "Writing multi-line file",
  "tool": "write_file",
  "args": {
    "path": "app.py",
    "content": "from flask import Flask\n\napp = Flask(__name__)\n\n@app.route('/')\ndef home(): return 'ok'"
  }
}"""
    data = _extract_tool_call(raw)
    assert data is not None
    assert data["tool"] == "write_file"
    assert "app = Flask" in data["args"]["content"]


def test_extract_final_answer():
    """Test extracting final answer block."""
    raw = """```json
{
  "thought": "All files created",
  "final_answer": "MedFrontier has been fully built with all 8 files."
}
```"""
    data = _extract_tool_call(raw)
    assert data is not None
    assert "MedFrontier has been fully built" in data["final_answer"]


# ---------------------------------------------------------------------------
# Workspace Approval & Scaffolding Tests
# ---------------------------------------------------------------------------

def test_workspace_tools_auto_approve_task(tmp_path):
    """Test that auto_approve_task=True allows multiple file writes without prompting."""
    tools = WorkspaceTools(root_dir=tmp_path)
    tools.auto_approve_task = True

    # Should write files without raising or prompting
    res1 = tools.write_file("file1.py", "print('hello 1')", require_approval=True)
    res2 = tools.write_file("file2.py", "print('hello 2')", require_approval=True)

    assert "Successfully wrote" in res1
    assert "Successfully wrote" in res2
    assert (tmp_path / "file1.py").exists()
    assert (tmp_path / "file2.py").exists()


# ---------------------------------------------------------------------------
# Agentic Loop Retry & Status Query Tests
# ---------------------------------------------------------------------------

def test_agent_retry_on_invalid_json_then_succeed(monkeypatch, tmp_path):
    """Test agent recovers when LLM outputs broken JSON on step 1, then fixes it on step 2."""
    agent = AgenticRouter(root_dir=tmp_path, require_approval=False)

    responses = [
        # Step 1: Broken JSON with missing closing quote and tool keyword
        GenerationResult(
            text='{"thought": "broken tool", "tool": "write_file", "args": {"path": "test.py", "content": broken}',
            model="gpt-4o",
            provider="openai",
            cost_usd=0.0001,
            latency_s=0.1,
            input_tokens=50,
            output_tokens=20,
        ),
        # Step 2: Fixed JSON
        GenerationResult(
            text='```json\n{"thought": "done", "final_answer": "Task successfully repaired and finished."}\n```',
            model="gpt-4o",
            provider="openai",
            cost_usd=0.0001,
            latency_s=0.1,
            input_tokens=50,
            output_tokens=20,
        ),
    ]

    call_idx = 0
    captured_prompts = []

    def mock_route(prompt, **kwargs):
        nonlocal call_idx
        captured_prompts.append(prompt)
        res = responses[min(call_idx, len(responses) - 1)]
        call_idx += 1
        return res

    monkeypatch.setattr("ijachi_router.agent.route", mock_route)

    result = agent.run("Create sample app", max_steps=4)
    assert result.completed is True
    assert "Task successfully repaired" in result.final_text
    # Verify the error retry instruction was sent to LLM on step 2
    assert len(captured_prompts) == 2
    assert "System Error: Invalid JSON syntax in tool call" in captured_prompts[1]


def test_agent_multiturn_goal_continuity(monkeypatch, tmp_path):
    """Test that sequential agent runs preserve project goals across turns."""
    cm = ContextManager(root_dir=tmp_path, memory_dir=tmp_path / "m")
    agent = AgenticRouter(root_dir=tmp_path, require_approval=False, context_manager=cm)

    # Turn 1: Build MedFrontier website
    turn1_res = GenerationResult(
        text='```json\n{"thought": "Built MedFrontier app.py", "final_answer": "Created MedFrontier Flask application."}\n```',
        model="gpt-4o",
        provider="openai",
        cost_usd=0.001,
        latency_s=0.2,
        input_tokens=100,
        output_tokens=50,
    )
    monkeypatch.setattr("ijachi_router.agent.route", lambda *args, **kwargs: turn1_res)
    agent.run("Build MedFrontier medical news website")

    # Turn 2: User asks "are you done with medfrontier website?"
    captured_prompt = []

    def mock_route2(prompt, **kwargs):
        captured_prompt.append(prompt)
        return GenerationResult(
            text='```json\n{"thought": "checking status", "final_answer": "Yes, MedFrontier is built with app.py."}\n```',
            model="gpt-4o",
            provider="openai",
            cost_usd=0.0005,
            latency_s=0.1,
            input_tokens=150,
            output_tokens=30,
        )

    monkeypatch.setattr("ijachi_router.agent.route", mock_route2)
    res2 = agent.run("are you done with the medfrontier website?")

    assert res2.completed is True
    # Verify the second turn received MedFrontier context in its prompt
    assert len(captured_prompt) > 0
    assert "MedFrontier" in captured_prompt[0]
    assert "Layer 2: Active Session & Intent" in captured_prompt[0]


def test_extract_files_from_markdown():
    """Test extracting file blocks from markdown tutorials."""
    from ijachi_router.agent import _extract_files_from_markdown

    markdown_doc = """
Below is the complete file structure for MedFrontier.

### File: `config.py`
```python
import os

class Config:
    SECRET_KEY = "medfrontier-secret"
```

### 2. `models.py`
```python
class Article:
    def __init__(self, title):
        self.title = title
```

## `templates/index.html`
```html
<!DOCTYPE html>
<html>
<body><h1>MedFrontier</h1></body>
</html>
```
"""
    extracted = _extract_files_from_markdown(markdown_doc)
    assert len(extracted) == 3
    paths = [p[0] for p in extracted]
    assert "config.py" in paths
    assert "models.py" in paths
    assert "templates/index.html" in paths
    assert "SECRET_KEY" in extracted[0][1]


def test_agent_auto_writes_markdown_code_blocks(monkeypatch, tmp_path):
    """Test that when a model outputs markdown code blocks, the agent extracts and writes them to disk."""
    agent = AgenticRouter(root_dir=tmp_path, require_approval=False)

    markdown_response = """
Here are the files for your application:

### File: `config.py`
```python
PORT = 8080
```

### File: `app.py`
```python
print("Hello World")
```
"""
    mock_res = GenerationResult(
        text=markdown_response,
        model="gemini-2.5-flash",
        provider="gemini",
        cost_usd=0.0001,
        latency_s=0.2,
        input_tokens=100,
        output_tokens=50,
    )
    monkeypatch.setattr("ijachi_router.agent.route", lambda *args, **kwargs: mock_res)

    res = agent.run("Create sample application")
    assert res.completed is True

    # Check that the files were actually created on disk
    config_file = tmp_path / "config.py"
    app_file = tmp_path / "app.py"
    assert config_file.exists()
    assert "PORT = 8080" in config_file.read_text()
    assert app_file.exists()
    assert 'print("Hello World")' in app_file.read_text()


def test_optimizer_preserves_agentic_prompt():
    """Test that optimize_prompt does not append conversational suffixes to agentic prompts."""
    from ijachi_router.optimizer import optimize_prompt, is_agentic_prompt

    agent_prompt = 'You are ijachi-code. {"tool": "write_file", "args": {"path": "app.py"}}'
    assert is_agentic_prompt(agent_prompt) is True
    optimized = optimize_prompt(agent_prompt, "gemini", "code")
    assert "Please respond clearly and accurately." not in optimized
    assert optimized == agent_prompt
