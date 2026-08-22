"""Unit tests for Final Platform Ecosystem Features (Streaming, Budget, SDK Gen, GitHub Auto)."""

from __future__ import annotations

from pathlib import Path
import pytest

from ijachi_router.budget import BudgetManager
from ijachi_router.sdk_generator import SDKGenerator
from ijachi_router.streaming import stream_route
from ijachi_router.github_automation import GitHubAutomation
from ijachi_router.providers.base import GenerationResult


def test_budget_manager(tmp_path):
    budget_file = tmp_path / "budget.json"
    bm = BudgetManager(budget_file=budget_file)

    bm.set_budget(15.0)
    assert bm.config.monthly_limit_usd == 15.0

    bm.record_spend(5.0)
    assert bm.config.accumulated_spend_usd == 5.0
    assert "Budget OK" in bm.summary()

    bm.record_spend(11.0)  # Total 16.0 >= 15.0 limit
    exceeded, msg = bm.check_budget_status()
    assert exceeded is True
    assert "Monthly budget hard cap" in msg


def test_sdk_generator(tmp_path):
    gen = SDKGenerator()

    # TypeScript
    msg_ts = gen.export_sdk("typescript", output_dir=tmp_path)
    assert "TypeScript" in msg_ts
    assert (tmp_path / "ijachi-llm-router.ts").exists()

    # Go
    msg_go = gen.export_sdk("go", output_dir=tmp_path)
    assert "Go" in msg_go
    assert (tmp_path / "router.go").exists()

    # Rust
    msg_rs = gen.export_sdk("rust", output_dir=tmp_path)
    assert "Rust" in msg_rs
    assert (tmp_path / "lib.rs").exists()


def test_stream_route(monkeypatch):
    mock_res = GenerationResult(
        text="Hello world test",
        model="gpt-4o",
        provider="openai",
        cost_usd=0.0001,
        latency_s=0.1,
        input_tokens=10,
        output_tokens=5,
    )

    def mock_route_stream(*args, **kwargs):
        yield "Hello "
        yield "world "
        yield "test"
        yield mock_res

    monkeypatch.setattr("ijachi_router.streaming.route_stream", mock_route_stream)

    items = list(stream_route("Test prompt"))
    str_chunks = [i for i in items if isinstance(i, str)]
    assert len(str_chunks) == 3
    assert "".join(str_chunks) == "Hello world test"
