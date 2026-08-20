"""Unit and integration tests for ijachi-code Agentic Workspace Engine."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from ijachi_router.agent import AgenticRouter, WorkspaceTools
from ijachi_router.providers.base import GenerationResult


@pytest.fixture
def temp_workspace(tmp_path):
    """Fixture providing a temporary workspace directory with test files."""
    test_file = tmp_path / "sample.py"
    test_file.write_text("def hello():\n    print('Hello World')\n", encoding="utf-8")
    return tmp_path


def test_workspace_tools_read_and_write(temp_workspace):
    tools = WorkspaceTools(root_dir=temp_workspace)

    # Test read_file
    content = tools.read_file("sample.py")
    assert "Hello World" in content

    # Test write_file
    res = tools.write_file("new_module.py", "x = 42\n", require_approval=False)
    assert "Successfully wrote" in res
    assert (temp_workspace / "new_module.py").read_text() == "x = 42\n"


def test_workspace_tools_edit_file(temp_workspace):
    tools = WorkspaceTools(root_dir=temp_workspace)
    res = tools.edit_file(
        "sample.py",
        target_content="Hello World",
        replacement_content="Hello Agentic World",
        require_approval=False,
    )
    assert "Successfully applied edit" in res
    assert "Hello Agentic World" in (temp_workspace / "sample.py").read_text()


def test_workspace_tools_list_and_grep(temp_workspace):
    tools = WorkspaceTools(root_dir=temp_workspace)
    listing = tools.list_dir(".")
    assert "sample.py" in listing

    grep_res = tools.grep_search("hello", ".")
    assert "sample.py:1" in grep_res


def test_agentic_router_loop(monkeypatch, temp_workspace):
    """Test AgenticRouter multi-step loop with mocked model responses."""
    tools = WorkspaceTools(root_dir=temp_workspace)
    agent = AgenticRouter(root_dir=temp_workspace, require_approval=False)

    step1_json = json.dumps({
        "thought": "Let us read sample.py first",
        "tool": "read_file",
        "args": {"path": "sample.py"}
    })
    step2_json = json.dumps({
        "thought": "Work completed successfully",
        "final_answer": "Checked sample.py successfully."
    })

    responses = [
        GenerationResult(text=f"```json\n{step1_json}\n```", model="gpt-4o-mini", provider="openai", cost_usd=0.0001, latency_s=0.1, input_tokens=100, output_tokens=50),
        GenerationResult(text=f"```json\n{step2_json}\n```", model="gpt-4o-mini", provider="openai", cost_usd=0.0001, latency_s=0.1, input_tokens=100, output_tokens=50),
    ]

    mock_call_idx = 0
    def mock_route(*args, **kwargs):
        nonlocal mock_call_idx
        res = responses[min(mock_call_idx, len(responses) - 1)]
        mock_call_idx += 1
        return res

    monkeypatch.setattr("ijachi_router.agent.route", mock_route)

    result = agent.run("Analyze sample.py", max_steps=5)
    assert result.completed is True
    assert "Checked sample.py successfully" in result.final_text
    assert len(result.steps) == 1
    assert result.steps[0].tool_name == "read_file"
