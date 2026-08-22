"""Unit tests for ijachi_router/plan_mode.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ijachi_router.plan_mode import PlanModePlanner, is_plan_mode, PlanPreview


@pytest.fixture
def planner(tmp_path):
    return PlanModePlanner(workspace_root=tmp_path, accessible=True)


def test_is_plan_mode():
    assert is_plan_mode("plan") is True
    assert is_plan_mode("auto") is False
    assert is_plan_mode("Plan") is True


def test_plan_writes_file_and_returns_preview(planner, tmp_path):
    fake_response = "# Plan\n\n1. Do A\n2. Do B\n"
    with patch("ijachi_router.plan_mode.route", return_value=MagicTextResult(fake_response)):
        preview = planner.plan("Build feature X")

    assert preview.plan_path == tmp_path / ".claude" / "plan.md"
    assert preview.total_lines == 4
    assert preview.plan_path.exists()
    assert "# Plan" in preview.plan_path.read_text(encoding="utf-8")


def test_confirm_plan_approved(monkeypatch, planner, tmp_path):
    plan_file = tmp_path / ".claude" / "plan.md"
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text("# Plan\nstep\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _="": "y")
    assert planner.confirm_plan() is True


def test_confirm_plan_rejected(monkeypatch, planner, tmp_path):
    plan_file = tmp_path / ".claude" / "plan.md"
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text("# Plan\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _="": "n")
    assert planner.confirm_plan() is False


def test_generate_claude_md(planner, tmp_path):
    fake_response = "# Project Context\n\nOverview.\n"
    with patch("ijachi_router.plan_mode.route", return_value=MagicTextResult(fake_response)):
        path = planner.generate_claude_md()
    assert path == tmp_path / "CLAUDE.md"
    assert path.exists()


def test_clear_plan(planner, tmp_path):
    preview = planner.plan("Task")
    assert preview.plan_path.exists()
    planner.clear_plan()
    assert not preview.plan_path.exists()


class MagicTextResult:
    """Tiny stand-in for a routing result with a `.text` attribute."""

    def __init__(self, text: str):
        self.text = text
