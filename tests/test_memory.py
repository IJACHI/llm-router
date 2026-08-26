"""Unit tests for Persistent Project Memory & Context Compressor Engine."""

from __future__ import annotations

from pathlib import Path
import pytest

from ijachi_router.memory import ProjectMemory


def test_project_memory_lifecycle(tmp_path):
    mem = ProjectMemory(root_dir=tmp_path, session_id="test_session", memory_dir=tmp_path / "mem")
    assert mem.project_name == tmp_path.name
    assert mem.session_id == "test_session"

    # Add interaction turns
    mem.add_turn("How do I sort a list in Python?", "Use list.sort() or sorted().", model="gpt-4o")
    assert len(mem.turns) == 1

    # Reload memory from disk
    mem2 = ProjectMemory(root_dir=tmp_path, session_id="test_session", memory_dir=tmp_path / "mem")
    assert len(mem2.turns) == 1
    assert mem2.turns[0].prompt == "How do I sort a list in Python?"


def test_memory_token_compression(tmp_path, monkeypatch):
    mem = ProjectMemory(root_dir=tmp_path, session_id="compress_test", memory_dir=tmp_path / "mem")

    from ijachi_router.providers.base import GenerationResult
    mock_res = GenerationResult(
        text="- Configured architectural modules\n- Saved dependencies",
        model="gpt-4o",
        provider="openai",
        cost_usd=0.0001,
        latency_s=0.01,
        input_tokens=50,
        output_tokens=20,
    )
    import ijachi_router.core
    monkeypatch.setattr("ijachi_router.core.route", lambda *args, **kwargs: mock_res)

    # Add long prompts to cross threshold
    for i in range(10):
        mem.add_turn(
            f"Step {i}: Explain architectural detail and setup requirement in depth for item {i}",
            f"Result for step {i}: Configured module successfully with all dependencies.",
            model="gpt-4o",
        )

    mem.compress_if_needed(threshold_tokens=200)
    assert mem.compressed_digest != ""
    assert len(mem.compressed_digest) > 20
    assert mem.total_tokens_saved > 0

    ctx = mem.get_compressed_context()
    assert "PREVIOUS SESSION MEMORY" in ctx


def test_memory_clear(tmp_path):
    mem = ProjectMemory(root_dir=tmp_path, session_id="clear_test", memory_dir=tmp_path / "mem")
    mem.add_turn("Prompt", "Response")
    assert len(mem.turns) == 1

    mem.clear()
    assert len(mem.turns) == 0
    assert mem.compressed_digest == ""

    summary = mem.summary()
    assert "Active Turns in Memory: 0" in summary
