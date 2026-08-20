"""Unit tests for Workspace Symbol Indexer, Multi-Model Consensus, and Test Auto-Repair."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from ijachi_router.indexer import WorkspaceIndexer
from ijachi_router.consensus import consensus_route
from ijachi_router.agent import AgenticRouter
from ijachi_router.providers.base import GenerationResult


def test_workspace_indexer(tmp_path):
    code_file = tmp_path / "app.py"
    code_file.write_text(
        "class RouterEngine:\n"
        "    pass\n\n"
        "def main_process():\n"
        "    print('running')\n",
        encoding="utf-8",
    )

    indexer = WorkspaceIndexer(root_dir=tmp_path)
    symbols = indexer.index_workspace()

    assert len(symbols) == 2
    names = {s.name for s in symbols}
    assert "RouterEngine" in names
    assert "main_process" in names

    summary = indexer.get_summary()
    assert "RouterEngine" in summary


def test_consensus_route_identical_models(monkeypatch):
    """Test consensus_route when both calls yield same result."""
    res_mock = GenerationResult(
        text="def add(a, b):\n    return a + b",
        model="gpt-4o",
        provider="openai",
        cost_usd=0.0001,
        latency_s=0.1,
        input_tokens=50,
        output_tokens=20,
    )

    monkeypatch.setattr("ijachi_router.consensus.route", lambda *args, **kwargs: res_mock)

    res = consensus_route("Write add function")
    assert res.consensus_model == "gpt-4o"
    assert "def add" in res.final_text


def test_agent_git_and_fix_tests(monkeypatch, tmp_path):
    agent = AgenticRouter(root_dir=tmp_path, require_approval=False)

    # Test fix_tests when command passes
    def mock_run_command(cmd, **kwargs):
        if cmd == "pytest":
            return "Exit Code: 0\n1 passed"
        return "Exit Code: 0"

    monkeypatch.setattr(agent.tools, "run_command", mock_run_command)
    res = agent.fix_tests("pytest", max_retries=2)
    assert res.completed is True
    assert "passed successfully" in res.final_text
