"""Unit tests for task telemetry, token counting, cost savings calculations, and breakdown rendering."""

from __future__ import annotations

import pytest
from ijachi_router.providers.base import GenerationResult
from ijachi_router.agent import AgentStep, AgentResult
from ijachi_router.ui import render_route_footer, render_agent_breakdown, set_theme


def test_generation_result_telemetry_properties():
    res = GenerationResult(
        text="Hello world",
        provider="groq",
        model="llama-3.3-70b-versatile",
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.0001,
        latency_s=0.5,
        category="code",
        complexity=0.8,
        cost_saved_usd=0.0034,
        savings_pct=97.1,
        tokens_per_sec=600.0,
        baseline_model="gpt-4o",
        baseline_cost_usd=0.0035,
    )
    assert res.total_tokens == 300
    assert res.cost_saved_usd == 0.0034
    assert res.savings_pct == 97.1
    assert res.tokens_per_sec == 600.0


def test_agent_result_aggregation_and_breakdown():
    step1 = AgentStep(
        step_number=1,
        thought="Reading file",
        tool_name="read_file",
        tool_args={"path": "app.py"},
        tool_output="print(1)",
        model_used="gpt-4o-mini",
        provider="openai",
        cost_usd=0.0002,
        input_tokens=200,
        output_tokens=100,
        cost_saved_usd=0.0023,
        latency_s=0.4,
    )
    step2 = AgentStep(
        step_number=2,
        thought="Editing file",
        tool_name="edit_file",
        tool_args={"path": "app.py"},
        tool_output="done",
        model_used="gpt-4o-mini",
        provider="openai",
        cost_usd=0.0003,
        input_tokens=300,
        output_tokens=150,
        cost_saved_usd=0.0034,
        latency_s=0.6,
    )

    res = AgentResult(
        final_text="Task finished successfully",
        steps=[step1, step2],
        total_cost_usd=0.0005,
        total_input_tokens=500,
        total_output_tokens=250,
        total_cost_saved_usd=0.0057,
        total_latency_s=1.0,
    )

    assert res.total_tokens == 750
    assert res.total_cost_usd == 0.0005
    assert res.total_cost_saved_usd == 0.0057
    assert res.savings_pct > 90.0

    # Ensure get_breakdown_table returns a valid Rich Table
    table = res.get_breakdown_table()
    assert table is not None
    assert len(table.columns) == 7


def test_render_telemetry_ui_helpers(capsys):
    res = GenerationResult(
        text="Sample output",
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=150,
        output_tokens=50,
        cost_usd=0.0001,
        latency_s=0.25,
        category="code",
        cost_saved_usd=0.0014,
        savings_pct=93.3,
        tokens_per_sec=800.0,
    )

    # Standard dark theme render
    set_theme("dark")
    render_route_footer(res)

    # Accessible theme render
    set_theme("accessible")
    render_route_footer(res)
    captured = capsys.readouterr()
    assert "telemetry:" in captured.out
    assert "gpt-4o-mini" in captured.out

    # Reset theme
    set_theme("dark")
