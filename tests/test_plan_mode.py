"""Tests for the plan-mode planner."""

from __future__ import annotations

from pathlib import Path

import pytest

from ijachi_router.plan_mode import PlanModePlanner, is_plan_mode, PlanPreview


def test_is_plan_mode_detects_plan_flag():
    """is_plan_mode normalizes whitespace/case and returns True for plan mode."""
    assert is_plan_mode("plan") is True
    assert is_plan_mode(" Plan ") is True
    assert is_plan_mode("auto") is False
    assert is_plan_mode("manual") is False


def test_planner_paths(tmp_path):
    """The planner resolves workspace_root and plan file paths."""
    planner = PlanModePlanner(workspace_root=tmp_path, accessible=True)
    assert planner.workspace_root == tmp_path.resolve()
    assert planner.plan_dir == tmp_path / ".router"
    assert planner.plan_file == tmp_path / ".router" / "plan.md"


@pytest.fixture
def planner(tmp_path):
    """Return an accessible planner using a temp workspace."""
    return PlanModePlanner(workspace_root=tmp_path, accessible=True)


def test_confirm_plan_accessible_yes(monkeypatch, planner):
    """confirm_plan in accessible mode reads user input and approves."""
    preview = PlanPreview(
        task="test",
        plan_path=planner.plan_file,
        total_lines=5,
        preview_lines=["line 1"],
    )
    monkeypatch.setattr("builtins.input", lambda: "y")
    assert planner.confirm_plan(preview) is True
    assert preview.approved is True


def test_confirm_plan_accessible_no(monkeypatch, planner):
    """confirm_plan in accessible mode handles a 'no' response."""
    preview = PlanPreview(
        task="test",
        plan_path=planner.plan_file,
        total_lines=5,
        preview_lines=["line 1"],
    )
    monkeypatch.setattr("builtins.input", lambda: "n")
    assert planner.confirm_plan(preview) is False
    assert preview.approved is False


def test_generate_agents_md_writes_file(tmp_path):
    """generate_agents_md writes an AGENTS.md file in the workspace root."""
    planner = PlanModePlanner(workspace_root=tmp_path, accessible=True)
    path = planner.generate_agents_md("A small test project.")
    assert path == tmp_path / "AGENTS.md"
    assert path.exists()
    assert len(path.read_text(encoding="utf-8")) > 0
