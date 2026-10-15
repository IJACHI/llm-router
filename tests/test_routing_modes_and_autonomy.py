"""Tests for User-Configurable Routing Preference Modes and Autonomy Levels.

Covers:
1. 4 Routing Preference Modes:
   - efficient (Default): Balances cost and best fit (cheapest adequate model)
   - cheapest: Preference for only cheapest/free models
   - best: Preference for best models/providers (high quality bias)
   - best-fit: Best fit models/providers for the task irrespective of cost
2. 3 Autonomy Levels:
   - auto (Fully automatic): No need for user approvals for safe actions
   - semi-auto (Semi-automatic): Approvals for some activities (auto-approves edits, asks for shell)
   - manual (Manual): Needs approval for every major activity
3. REPL commands and interactive toggling (/mode, /autonomy, /auto).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from ijachi_router.agent.permissions import PermissionManager, normalize_permission_mode
from ijachi_router.config import ModelConfig, normalize_mode
from ijachi_router.routing.features import extract_session_need
from ijachi_router.routing.policy import filter_candidates
from ijachi_router.routing.scorer import score_candidate
from ijachi_router.session.state import SessionState
from ijachi_router.session.store import SessionStore
from ijachi_router.ui.render import format_status_line
from ijachi_router.ui.repl import InteractiveREPL


def test_normalize_mode_aliases():
    assert normalize_mode(None) == "efficient"
    assert normalize_mode("") == "efficient"
    assert normalize_mode("efficient") == "efficient"
    assert normalize_mode("balanced") == "efficient"
    assert normalize_mode("1") == "efficient"

    assert normalize_mode("cheapest") == "cheapest"
    assert normalize_mode("cost") == "cheapest"
    assert normalize_mode("free") == "cheapest"
    assert normalize_mode("2") == "cheapest"

    assert normalize_mode("best") == "best"
    assert normalize_mode("quality") == "best"
    assert normalize_mode("pro") == "best"
    assert normalize_mode("3") == "best"

    assert normalize_mode("best-fit") == "best-fit"
    assert normalize_mode("unconstrained") == "best-fit"
    assert normalize_mode("max-quality") == "best-fit"
    assert normalize_mode("4") == "best-fit"


def test_four_routing_modes_scoring():
    free_adequate = ModelConfig(
        provider="local",
        model_id="qwen2.5-coder:7b",
        tags=["code"],
        input_per_1k=0.0,
        output_per_1k=0.0,
        max_context=32768,
        speed_tier="fast",
        quality_tier=2,
    )
    frontier_expensive = ModelConfig(
        provider="anthropic",
        model_id="claude-sonnet-4-5",
        tags=["code", "reasoning"],
        input_per_1k=0.010,
        output_per_1k=0.050,
        max_context=200000,
        speed_tier="medium",
        quality_tier=4,
    )
    state = SessionState(session_id="test_modes")
    need = extract_session_need("refactor database layer", state, "code", 0.9, 0.5)

    # 1. Cheapest mode: Free model wins overwhelmingly
    s_free_cheap = score_candidate(free_adequate, need, priority="cheapest")
    s_front_cheap = score_candidate(frontier_expensive, need, priority="cheapest")
    assert s_free_cheap > s_front_cheap

    # 2. Best mode: Frontier quality model wins despite price
    s_free_best = score_candidate(free_adequate, need, priority="best")
    s_front_best = score_candidate(frontier_expensive, need, priority="best")
    assert s_front_best > s_free_best

    # 3. Best-Fit mode: Irrespective of cost (pure quality + capability fit)
    s_free_fit = score_candidate(free_adequate, need, priority="best-fit")
    s_front_fit = score_candidate(frontier_expensive, need, priority="best-fit")
    assert s_front_fit > s_free_fit

    # 4. Efficient mode (Default): For moderate complexity (0.5), free adequate model wins
    s_free_eff = score_candidate(free_adequate, need, priority="efficient")
    s_front_eff = score_candidate(frontier_expensive, need, priority="efficient")
    assert s_free_eff > s_front_eff


def test_best_fit_mode_bypasses_cost_cap():
    expensive_model = ModelConfig(
        provider="anthropic",
        model_id="claude-sonnet-4-5",
        tags=["code"],
        input_per_1k=0.01,
        output_per_1k=0.05,
        max_context=200000,
        speed_tier="medium",
        quality_tier=4,
    )
    state = SessionState(session_id="test_cap")
    need = extract_session_need("complex refactor", state, "code", 0.9, 0.7)

    # In efficient mode with $0.0001 cap: filtered out
    eligible_eff, reasons_eff = filter_candidates(
        candidates=[expensive_model],
        need=need,
        max_cost_per_turn=0.0001,
        priority="efficient",
    )
    assert len(eligible_eff) == 0

    # In best-fit mode: cost cap is bypassed irrespective of cost
    eligible_fit, reasons_fit = filter_candidates(
        candidates=[expensive_model],
        need=need,
        max_cost_per_turn=0.0001,
        priority="best-fit",
    )
    assert len(eligible_fit) == 1
    assert eligible_fit[0].model_id == "claude-sonnet-4-5"


def test_autonomy_modes_authorization(tmp_path):
    # 1. Fully Automatic mode: File edits and safe bash commands run without approval
    pm_auto = PermissionManager(mode="auto", is_tty=True)
    res_edit = pm_auto.authorize_tool_call("Edit", {"path": "main.py"}, workspace_dir=tmp_path)
    assert res_edit.allowed is True

    res_bash = pm_auto.authorize_tool_call("Bash", {"command": "pytest"}, workspace_dir=tmp_path)
    assert res_bash.allowed is True

    # 2. Semi-Automatic mode: File edits auto-approved, but shell execution prompts
    pm_semi = PermissionManager(mode="semi-auto", is_tty=False)
    res_semi_edit = pm_semi.authorize_tool_call("Edit", {"path": "main.py"}, workspace_dir=tmp_path)
    assert res_semi_edit.allowed is True

    # Non-interactive without TTY, shell execution is denied (prompts in TTY)
    res_semi_bash = pm_semi.authorize_tool_call("Bash", {"command": "pytest"}, workspace_dir=tmp_path)
    assert res_semi_bash.allowed is False

    # 3. Manual mode: Needs approval for every major activity
    pm_manual = PermissionManager(mode="manual", is_tty=False)
    res_man_edit = pm_manual.authorize_tool_call("Edit", {"path": "main.py"}, workspace_dir=tmp_path)
    assert res_man_edit.allowed is False


def test_repl_mode_and_autonomy_toggle(tmp_path):
    store = SessionStore(workspace_dir=tmp_path)
    repl = InteractiveREPL(store=store, priority="efficient", permission_mode="manual")

    # Initial state
    assert repl.state.priority == "efficient"
    assert repl.loop.permissions.mode == "manual"

    # Toggle autonomy via /auto
    repl.handle_slash_command("/auto")
    assert repl.loop.permissions.mode == "semi-auto"

    repl.handle_slash_command("/auto")
    assert repl.loop.permissions.mode == "auto"

    repl.handle_slash_command("/auto")
    assert repl.loop.permissions.mode == "manual"

    # Switch mode via /mode
    repl.handle_slash_command("/mode cheapest")
    assert repl.state.priority == "cheapest"

    repl.handle_slash_command("/mode best-fit")
    assert repl.state.priority == "best-fit"

    # Switch autonomy explicitly via /autonomy
    repl.handle_slash_command("/autonomy auto")
    assert repl.loop.permissions.mode == "auto"

    # Verify status line displays both modes
    status = repl._toolbar_fn()
    assert "[best-fit | auto]" in status
