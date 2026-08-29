"""Tests for Phase 1-6 new modules: repl, planner, workspace_context, health, agent memory."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Phase 1: RichREPL slash commands
# ---------------------------------------------------------------------------

def test_repl_slash_commands_registered():
    from ijachi_router.repl import _SLASH_COMMANDS
    for name in ["/help", "/clear", "/status", "/providers", "/auto", "/plan", "/memory", "/compact"]:
        assert name in _SLASH_COMMANDS, f"Slash command {name} not registered"


def test_repl_clear_resets_cost():
    from ijachi_router.repl import RichREPL, _SLASH_COMMANDS
    repl = RichREPL()
    repl.session_cost = 9.99
    repl.history.append({"role": "user", "content": "test"})
    _SLASH_COMMANDS["/clear"].handler(repl, "")
    assert repl.session_cost == 0.0
    assert repl.history == []


def test_repl_auto_toggle():
    from ijachi_router.repl import RichREPL, _SLASH_COMMANDS
    repl = RichREPL()
    assert repl.auto_approve is False
    _SLASH_COMMANDS["/auto"].handler(repl, "")
    assert repl.auto_approve is True
    _SLASH_COMMANDS["/auto"].handler(repl, "")
    assert repl.auto_approve is False


def test_repl_plan_toggle():
    from ijachi_router.repl import RichREPL, _SLASH_COMMANDS
    repl = RichREPL()
    assert repl.plan_mode is False
    _SLASH_COMMANDS["/plan"].handler(repl, "")
    assert repl.plan_mode is True


def test_repl_is_agentic_task():
    from ijachi_router.repl import RichREPL
    repl = RichREPL()
    assert repl._is_agentic_task("build me a FastAPI service with authentication") is True
    assert repl._is_agentic_task("Hi") is False
    assert repl._is_agentic_task("What is the capital of France?") is False


# ---------------------------------------------------------------------------
# Phase 2: Planner
# ---------------------------------------------------------------------------

def test_plan_step_dataclass():
    from ijachi_router.planner import PlanStep
    step = PlanStep(index=1, description="Read workspace", tool_hint="list_dir", model_hint="fast")
    assert step.index == 1
    assert step.completed is False


def test_execution_plan_dataclass():
    from ijachi_router.planner import ExecutionPlan, PlanStep
    plan = ExecutionPlan(
        task="Build a web app",
        steps=[PlanStep(index=1, description="Scaffold files", model_hint="fast")],
    )
    assert len(plan.steps) == 1
    assert plan.task == "Build a web app"


def test_render_plan_runs_without_error():
    """render_plan should not raise."""
    from ijachi_router.planner import ExecutionPlan, PlanStep, render_plan
    plan = ExecutionPlan(
        task="Test task",
        steps=[
            PlanStep(index=1, description="Step 1", tool_hint="list_dir", model_hint="fast"),
            PlanStep(index=2, description="Step 2", tool_hint="write_file", model_hint="slow", cost_hint="~$0.01"),
        ],
    )
    render_plan(plan)  # Should not raise


# ---------------------------------------------------------------------------
# Phase 3: Workspace Context
# ---------------------------------------------------------------------------

def test_load_workspace_context_missing():
    from ijachi_router.workspace_context import load_workspace_context
    with tempfile.TemporaryDirectory() as tmpdir:
        result = load_workspace_context(tmpdir)
        assert result is None


def test_load_workspace_context_ijachi_md():
    from ijachi_router.workspace_context import load_workspace_context
    with tempfile.TemporaryDirectory() as tmpdir:
        ctx_file = Path(tmpdir) / "IJACHI.md"
        ctx_file.write_text("# My Project\n- Language: Python\n")
        result = load_workspace_context(tmpdir)
        assert result is not None
        assert "My Project" in result
        assert "IJACHI.md" in result


def test_load_workspace_context_claude_md():
    from ijachi_router.workspace_context import load_workspace_context
    with tempfile.TemporaryDirectory() as tmpdir:
        ctx_file = Path(tmpdir) / "CLAUDE.md"
        ctx_file.write_text("# CLAUDE context\n- Use pytest\n")
        result = load_workspace_context(tmpdir)
        assert result is not None
        assert "CLAUDE context" in result


def test_detect_workspace_info_python():
    from ijachi_router.workspace_context import detect_workspace_info
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "pyproject.toml").write_text("[project]\nname=\"test\"\n")
        info = detect_workspace_info(Path(tmpdir))
        assert info["language"] == "Python"
        assert info["test_command"] == "pytest"


# ---------------------------------------------------------------------------
# Phase 4: Session Memory
# ---------------------------------------------------------------------------

def test_save_and_load_memory():
    from ijachi_router.agent import save_memory, load_memory
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = str(tmpdir) + "/myproject"
        # Patch _MEMORY_DIR to use temp
        import ijachi_router.agent as agent_mod
        orig = agent_mod._MEMORY_DIR
        agent_mod._MEMORY_DIR = Path(tmpdir) / "memory"
        try:
            save_memory(workspace, "Task: Build API. Result: Created FastAPI service.")
            result = load_memory(workspace)
            assert result is not None
            assert "FastAPI" in result
        finally:
            agent_mod._MEMORY_DIR = orig


def test_save_memory_rolling_limit():
    """Verify memory only keeps last 5 entries."""
    from ijachi_router.agent import save_memory, load_memory
    import ijachi_router.agent as agent_mod
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = str(tmpdir) + "/myproject"
        orig = agent_mod._MEMORY_DIR
        agent_mod._MEMORY_DIR = Path(tmpdir) / "memory"
        try:
            for i in range(7):
                save_memory(workspace, f"Entry {i}")
            result = load_memory(workspace)
            assert result is not None
            entries = [e.strip() for e in result.split("---") if e.strip()]
            assert len(entries) <= 5
        finally:
            agent_mod._MEMORY_DIR = orig


# ---------------------------------------------------------------------------
# Phase 5: Provider Health
# ---------------------------------------------------------------------------

def test_provider_status_dataclass():
    from ijachi_router.health import ProviderStatus
    s = ProviderStatus(
        provider="gemini",
        model_id="gemini-3.6-flash",
        available=True,
        has_key=True,
        selected=True,
    )
    assert s.selected is True


def test_check_providers_quick_returns_list():
    from ijachi_router.health import check_providers_quick
    from ijachi_router.config import load_config
    cfg = load_config()
    statuses = check_providers_quick(cfg)
    assert isinstance(statuses, list)
    assert len(statuses) > 0


def test_render_provider_card_no_error():
    from ijachi_router.health import render_provider_card, ProviderStatus
    statuses = [
        ProviderStatus("gemini", "gemini-3.6-flash", True, True, True, speed_tier="fast", cost_str="~free"),
        ProviderStatus("local", "deepseek-r1:7b", False, True, False, speed_tier="slow", cost_str="FREE"),
    ]
    render_provider_card(statuses)  # Should not raise


# ---------------------------------------------------------------------------
# Phase 6: AgenticRouter enhancements
# ---------------------------------------------------------------------------

def test_agentic_router_workspace_context_injection():
    from ijachi_router.agent import AgenticRouter
    agent = AgenticRouter(workspace_context="# My Project\n- Language: Python")
    prompt = agent._build_system_prompt()
    assert "My Project" in prompt


def test_agentic_router_no_workspace_context():
    from ijachi_router.agent import AgenticRouter
    agent = AgenticRouter()
    prompt = agent._build_system_prompt()
    assert "You are ijachi-code" in prompt
