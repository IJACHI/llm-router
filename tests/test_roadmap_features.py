"""Unit tests for Next-Gen Roadmap Features (Benchmarker, Swarm, DocGen, LSP)."""

from __future__ import annotations

from pathlib import Path
import pytest

from ijachi_router.benchmarker import BenchmarkEngine, BenchmarkResult
from ijachi_router.swarm import SwarmManager
from ijachi_router.docgen import DocGenerator
from ijachi_router.providers.base import GenerationResult


def test_benchmark_engine_formatting():
    engine = BenchmarkEngine()
    results = [
        BenchmarkResult("openai", "gpt-4o", 0.35, 85.0, 150, 0.0005, "success"),
        BenchmarkResult("anthropic", "claude-3-7-sonnet", 0.62, 60.0, 200, 0.0015, "success"),
    ]
    table = engine.format_table(results)
    assert "gpt-4o" in table
    assert "claude-3-7-sonnet" in table
    assert "85.0" in table


def test_swarm_manager(monkeypatch):
    mock_res = GenerationResult(
        text="Sample output text",
        model="gpt-4o",
        provider="openai",
        cost_usd=0.0001,
        latency_s=0.1,
        input_tokens=100,
        output_tokens=50,
    )
    monkeypatch.setattr("ijachi_router.swarm.route", lambda *args, **kwargs: mock_res)

    manager = SwarmManager()
    res = manager.run_swarm("Build authentication endpoint")

    assert res.completed is True
    assert len(res.phases) == 4
    agent_names = [p.agent_name for p in res.phases]
    assert "ArchitectAgent" in agent_names
    assert "DeveloperAgent" in agent_names
    assert "SecurityAgent" in agent_names
    assert "QATesterAgent" in agent_names


def test_doc_generator(tmp_path):
    (tmp_path / "main.py").write_text("class AppServer:\n    def start(): pass\n", encoding="utf-8")

    docgen = DocGenerator(root_dir=tmp_path)
    res_msg = docgen.generate_architecture_md()

    assert "Successfully generated" in res_msg
    arch_file = tmp_path / "ARCHITECTURE.md"
    assert arch_file.exists()
    content = arch_file.read_text(encoding="utf-8")
    assert "classDiagram" in content
    assert "sequenceDiagram" in content
    assert "AppServer" in content
