"""Unit tests for Three-Layer Context Memory Manager (L1 Global, L2 Session, L3 Task)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ijachi_router.context_manager import ContextManager, TaskTurn
from ijachi_router.memory import ProjectMemory, MemoryTurn
from ijachi_router.providers.base import GenerationResult


# ---------------------------------------------------------------------------
# Layer 1 (Global Disk Memory) Tests
# ---------------------------------------------------------------------------

def test_l1_memory_persistence(tmp_path):
    """Test that ProjectMemory writes and loads global memory state from disk."""
    mem_dir = tmp_path / "memory_store"
    mem1 = ProjectMemory(root_dir=tmp_path, memory_dir=mem_dir)

    mem1.add_architectural_decision("Use FastAPI with async SQLAlchemy")
    mem1.set_preference("style_guide", "google")
    mem1.add_turn(
        task="Create user model",
        response_text="Created UserModel with email and password hash",
        model="gpt-4o",
        cost_usd=0.002,
    )

    # Re-instantiate from same directory
    mem2 = ProjectMemory(root_dir=tmp_path, memory_dir=mem_dir)
    assert "FastAPI" in mem2.architectural_decisions[0]
    assert mem2.preferences.get("style_guide") == "google"
    assert len(mem2.turns) == 1
    assert mem2.turns[0].task == "Create user model"


def test_l1_memory_clear(tmp_path):
    """Test that clear() wipes disk and in-memory state."""
    mem_dir = tmp_path / "memory_store"
    mem = ProjectMemory(root_dir=tmp_path, memory_dir=mem_dir)
    mem.add_architectural_decision("Some decision")
    assert mem.memory_file.exists()

    mem.clear()
    assert not mem.memory_file.exists()
    assert len(mem.architectural_decisions) == 0


def test_l1_context_generation(tmp_path):
    """Test formatting of L1 context block."""
    mem = ProjectMemory(root_dir=tmp_path, memory_dir=tmp_path / "m")
    mem.global_digest = "Built authentication routes in session 1"
    mem.add_architectural_decision("Target Python 3.12+")

    ctx_text = mem.get_l1_context()
    assert "Previous session memory:" in ctx_text
    assert "Built authentication routes" in ctx_text
    assert "Target Python 3.12+" in ctx_text


# ---------------------------------------------------------------------------
# Layer 2 (Session Memory) & Model Switch Tests
# ---------------------------------------------------------------------------

def test_l2_session_goal_and_model_switch(tmp_path):
    """Test that session goal and model switch events are tracked in L2."""
    cm = ContextManager(root_dir=tmp_path, memory_dir=tmp_path / "m")
    cm.set_session_goal("Migrate database to Postgres")
    cm.record_model_switch("gpt-4o", "groq/llama-3.3-70b", reason="speed optimization")

    block = cm.build_context_block("next step")
    assert "Current Session Goal: Migrate database to Postgres" in block
    assert "Model Transition: Handed off from gpt-4o -> groq/llama-3.3-70b" in block


def test_l2_auto_sets_goal_from_first_task(tmp_path):
    """Test that the first task automatically anchors the session goal."""
    cm = ContextManager(root_dir=tmp_path, memory_dir=tmp_path / "m")
    cm.record_task("Build payment integration", "Created stripe webhook handler", "gpt-4o")

    assert cm.session_goal == "Build payment integration"
    block = cm.build_context_block()
    assert "Current Session Goal: Build payment integration" in block


# ---------------------------------------------------------------------------
# Layer 3 (Task Ring Buffer) Tests
# ---------------------------------------------------------------------------

def test_l3_task_ring_buffer_limit(tmp_path):
    """Test that L3 enforces the max task turn limit."""
    cm = ContextManager(root_dir=tmp_path, max_l3_turns=3, memory_dir=tmp_path / "m")

    for i in range(5):
        cm.record_task(f"Task #{i}", f"Result for task #{i}", "gpt-4o-mini")

    assert len(cm.l3_task_turns) == 3
    assert cm.l3_task_turns[0].task == "Task #2"
    assert cm.l3_task_turns[-1].task == "Task #4"


def test_context_block_omitted_when_empty(tmp_path):
    """Test that build_context_block returns an empty string on fresh start."""
    cm = ContextManager(root_dir=tmp_path, memory_dir=tmp_path / "m")
    assert cm.build_context_block() == ""


# ---------------------------------------------------------------------------
# AgenticRouter Integration Tests
# ---------------------------------------------------------------------------

def test_agentic_router_context_injection(monkeypatch, tmp_path):
    """Test that AgenticRouter injects the multi-layer context block into prompts."""
    from ijachi_router.agent import AgenticRouter

    cm = ContextManager(root_dir=tmp_path, memory_dir=tmp_path / "m")
    cm.set_session_goal("Refactor auth module")
    cm.l1_global.add_architectural_decision("Use JWT bearer tokens")

    agent = AgenticRouter(
        root_dir=tmp_path,
        require_approval=False,
        context_manager=cm,
    )

    captured_prompt = []

    def mock_route(prompt, **kwargs):
        captured_prompt.append(prompt)
        return GenerationResult(
            text='```json\n{"thought": "done", "final_answer": "Finished refactoring"}\n```',
            model="gpt-4o-mini",
            provider="openai",
            cost_usd=0.0001,
            latency_s=0.1,
            input_tokens=100,
            output_tokens=50,
        )

    monkeypatch.setattr("ijachi_router.agent.route", mock_route)

    result = agent.run("Add token refresh endpoint", max_steps=2)
    assert result.completed is True

    # Verify context block was injected into the LLM prompt
    assert len(captured_prompt) > 0
    full_prompt = captured_prompt[0]
    assert "--- IJACHI CONTEXT & PERSISTENT MEMORY ---" in full_prompt
    assert "Refactor auth module" in full_prompt
    assert "Use JWT bearer tokens" in full_prompt

    # Verify task was recorded in memory
    assert len(cm.l3_task_turns) == 1
    assert cm.l3_task_turns[0].task == "Add token refresh endpoint"


def test_agent_model_switch_recording(tmp_path):
    """Test that agent.set_model records a model transition in ContextManager."""
    from ijachi_router.agent import AgenticRouter

    cm = ContextManager(root_dir=tmp_path, memory_dir=tmp_path / "m")
    agent = AgenticRouter(root_dir=tmp_path, context_manager=cm)

    agent.set_model("groq/llama-3.3-70b")
    assert len(cm.session_model_switches) == 1
    assert cm.session_model_switches[0]["to"] == "groq/llama-3.3-70b"
