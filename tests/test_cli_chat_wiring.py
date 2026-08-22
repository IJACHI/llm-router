"""Integration tests for the chat command's enhanced UI wiring.

These tests exercise ``cli.chat_cmd`` with lightweight real fakes instead of
full MagicMocks to avoid boolean/repr pitfalls in a long-running REPL loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import pytest
from click.testing import CliRunner

import cli


@dataclass
class _FakeAgentResult:
    final_text: str = "done"
    steps: list[Any] = field(default_factory=list)
    total_cost_usd: float = 0.0
    completed: bool = True


@dataclass
class _FakeStep:
    model_used: str = "fake-model"
    provider: str = "fake-provider"


class _FakeAgent:
    """Minimal stand-in for AgenticRouter in the chat loop."""

    def __init__(self, *args, **kwargs):
        self.tools = type("Tools", (), {"root_dir": Path("/tmp")})()
        self.background = type("BG", (), {"active_count": lambda self: 0})()
        self.planner = type(
            "Planner",
            (),
            {"generate_claude_md": lambda self: Path("/tmp/CLAUDE.md")},
        )()
        self.checklist = type("CL", (), {"render": lambda self: None})()
        self.ctx = type(
            "Ctx",
            (),
            {
                "summary": lambda self: "",
                "build_context_block": lambda self: "",
                "clear": lambda self: None,
                "set_session_goal": lambda self, x: None,
                "record_task": lambda self, **kw: None,
                "l1_global": type(
                    "L1", (), {"add_architectural_decision": lambda self, x: None}
                )(),
            },
        )()
        self.force_model = None
        self.priority = "balanced"
        self.permission_mode = kwargs.get("permission_mode", "manual")

    def run(self, task: str):
        return _FakeAgentResult(
            final_text="hello",
            steps=[_FakeStep()],
            total_cost_usd=0.001,
        )

    def set_model(self, model_id):
        self.force_model = model_id

    def set_priority(self, priority):
        self.priority = priority

    def set_permission_mode(self, mode):
        self.permission_mode = mode


class _FakeEngine:
    """Minimal stand-in for PromptEngine."""

    def __init__(self, inputs: list[str | None]):
        self._inputs: Iterator[str | None] = iter(inputs)
        self.prompt_calls: list[dict[str, Any]] = []
        self.permission_mode = "manual"
        self.model = "unknown"
        self._set_permission_mode_calls: list[str] = []

    def prompt(self, *args, **kwargs):
        self.prompt_calls.append(kwargs)
        try:
            return next(self._inputs)
        except StopIteration:
            return "exit"

    def resolve_pastes(self, text: str):
        return text

    def update_cost(self, cost_usd: float):
        pass

    def set_permission_mode(self, mode: str):
        self._set_permission_mode_calls.append(mode)
        self.permission_mode = mode


class _FakeSkillManager:
    def __init__(self, *args, **kwargs):
        pass

    def list_skills(self):
        return []

    def print_skills_table(self):
        pass


class _FakeTranscript:
    def __init__(self, *args, **kwargs):
        pass

    def add_user_turn(self, content: str):
        pass

    def add_assistant_turn(self, **kwargs):
        pass

    def view(self):
        pass

    def save(self):
        return "/tmp/transcript.jsonl"


class _FakeConfig:
    style_guide = "pep8"
    accessibility = False
    theme = "dark"
    vim_mode = False
    auto_format = True
    require_comments = True

    @staticmethod
    def available_models():
        return []


def _patch_chat_deps(monkeypatch, fake_agent, engine):
    """Apply the source-module monkeypatches needed by ``chat_cmd``."""
    monkeypatch.setattr("ijachi_router.ui.print_welcome_card", lambda **kw: None)
    monkeypatch.setattr("ijachi_router.config.load_config", lambda: _FakeConfig())
    monkeypatch.setattr("ijachi_router.transcript.Transcript", _FakeTranscript)
    monkeypatch.setattr("ijachi_router.skill_manager.SkillManager", _FakeSkillManager)
    monkeypatch.setattr("ijachi_router.agent.AgenticRouter", lambda *a, **kw: fake_agent)
    monkeypatch.setattr(
        "ijachi_router.prompt_engine.PromptEngine", lambda *a, **kw: engine
    )


def test_chat_welcome_card_and_slash_init(monkeypatch):
    """Verify the chat command renders the welcome card and handles /init."""
    runner = CliRunner()
    engine = _FakeEngine(["/init", "hi", "exit"])
    fake_agent = _FakeAgent()
    _patch_chat_deps(monkeypatch, fake_agent, engine)

    result = runner.invoke(cli.chat_cmd, [])

    assert result.exit_code == 0, result.output
    # The real turn should have updated history counters and accept-edits flag
    assert len(engine.prompt_calls) == 3
    last_call = engine.prompt_calls[-1]
    assert last_call["history_total"] == 1
    assert last_call["history_index"] == 1
    assert last_call["accept_edits_on"] is False
    assert last_call["cost_usd"] == pytest.approx(0.001)


def test_chat_mode_cycle_syncs_agent(monkeypatch):
    """Verify /mode updates both the engine and the agent."""
    runner = CliRunner()
    engine = _FakeEngine(["/mode", "hi", "exit"])
    fake_agent = _FakeAgent()
    _patch_chat_deps(monkeypatch, fake_agent, engine)

    result = runner.invoke(cli.chat_cmd, [])

    assert result.exit_code == 0, result.output
    assert fake_agent.permission_mode == "accept-edits"
    assert engine.permission_mode == "accept-edits"
