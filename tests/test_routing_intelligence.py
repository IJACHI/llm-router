"""Tests for Document 2.4 & Document 3.6: Routing Intelligence and Policies.

Covers:
- FR-20: Session-aware routing features
- FR-23 & Doc 3.6: Candidate scoring with stickiness bonus
- FR-24: Agent quality floor filter
- FR-26 & AT-07: Escalation triggers after consecutive failures
- FR-29 & Doc 6.5: /why explanation structures
- FR-08 & T-13: Repetition detector for infinite loops
- SEC-13 & AT-14: --local-only policy enforcement
"""

from __future__ import annotations

from ijachi_router.agent.limits import RepetitionDetector
from ijachi_router.config import ModelConfig
from ijachi_router.routing.escalation import EscalationTracker
from ijachi_router.routing.explain import RoutingExplanation
from ijachi_router.routing.features import extract_session_need
from ijachi_router.routing.policy import filter_candidates
from ijachi_router.routing.scorer import score_candidate
from ijachi_router.session.state import SessionState


def test_session_aware_need_extraction():
    state = SessionState(session_id="test_need")
    state.record_file_read("src/auth.py")
    state.record_file_write("src/models.py")
    state.consecutive_tool_failures = 1

    # Prompt is brief ("fix it"), but session state indicates tool execution on existing files
    need = extract_session_need(
        prompt="fix it",
        state=state,
        category="code",
        confidence=0.85,
        complexity=0.7,
    )
    assert need.requires_tools is True
    assert "src/auth.py" in need.files_in_play
    assert need.has_prior_failures is True


def test_model_stickiness_bonus():
    model = ModelConfig(
        provider="anthropic",
        model_id="claude-sonnet-4-5",
        tags=["code", "reasoning"],
        input_per_1k=0.003,
        output_per_1k=0.015,
        max_context=200000,
        speed_tier="medium",
    )
    state = SessionState(session_id="test_sticky")
    need = extract_session_need("refactor", state, "code", 0.9, 0.5)

    # Score when NOT current model
    score_not_current = score_candidate(model, need, priority="balanced", is_current_model=False)

    # Score when current model with cached tokens
    score_current_cached = score_candidate(
        model, need, priority="balanced", is_current_model=True, cached_tokens=5000
    )

    # Current model must receive stickiness bonus
    assert score_current_cached > score_not_current


def test_agent_quality_floor():
    weak_model = ModelConfig(
        provider="openai",
        model_id="gpt-3.5-turbo",
        tags=["code", "simple-qa"],
        input_per_1k=0.0005,
        output_per_1k=0.0015,
        max_context=16000,
        speed_tier="fast",
    )
    setattr(weak_model, "quality_tier", 1)  # Below floor of 2

    state = SessionState(session_id="test_floor")
    need = extract_session_need("edit file", state, "code", 0.9, 0.6)
    need.requires_tools = True

    eligible, filtered_reasons = filter_candidates(
        candidates=[weak_model],
        need=need,
        agent_quality_floor=2,
    )
    assert len(eligible) == 0
    assert "below agent quality floor" in filtered_reasons.get("openai/gpt-3.5-turbo", "")


def test_local_only_policy_enforcement():
    cloud_model = ModelConfig(
        provider="anthropic",
        model_id="claude-haiku-4-5",
        tags=["code"],
        input_per_1k=0.001,
        output_per_1k=0.005,
        max_context=200000,
        speed_tier="fast",
    )
    local_model = ModelConfig(
        provider="local",
        model_id="llama3.1-8b",
        tags=["code"],
        input_per_1k=0.0,
        output_per_1k=0.0,
        max_context=128000,
        speed_tier="fast",
    )

    state = SessionState(session_id="test_local")
    need = extract_session_need("test", state, "code", 0.9, 0.4)

    eligible, filtered_reasons = filter_candidates(
        candidates=[cloud_model, local_model],
        need=need,
        local_only=True,
    )
    assert len(eligible) == 1
    assert eligible[0].provider == "local"
    assert "--local-only" in filtered_reasons.get("anthropic/claude-haiku-4-5", "")


def test_escalation_tracker_triggers_on_two_failures():
    tracker = EscalationTracker()
    assert tracker.is_escalated is False

    # First error
    d1 = tracker.record_tool_error()
    assert d1.escalate is False

    # Second error triggers escalation (FR-26)
    d2 = tracker.record_tool_error()
    assert d2.escalate is True
    assert "consecutive tool errors" in d2.reason
    assert tracker.is_escalated is True

    # 4 easy successes de-escalate back
    for _ in range(4):
        tracker.record_success(complexity=0.2)
    assert tracker.is_escalated is False


def test_repetition_detector_catches_three_identical_calls():
    detector = RepetitionDetector(threshold=3)

    call1 = detector.record_call_and_result("read_file", {"path": "main.py"}, "File contents line 1")
    assert call1 is False

    call2 = detector.record_call_and_result("read_file", {"path": "main.py"}, "File contents line 1")
    assert call2 is False

    # Third identical call triggers loop detection (FR-08)
    call3 = detector.record_call_and_result("read_file", {"path": "main.py"}, "File contents line 1")
    assert call3 is True


def test_routing_explanation_why_format():
    expl = RoutingExplanation(
        category="code-edit",
        confidence=0.88,
        complexity=0.62,
        requires_tools=True,
        session_files_count=3,
        current_model="claude-sonnet-4-5",
        filtered_out={"gpt-4o-mini": "below agent quality floor"},
        chosen_model="claude-sonnet-4-5",
        chosen_provider="anthropic",
        decision_reason="best fit; sticky bonus applied",
        tip="/priority cost would choose gemini-2.5-pro",
    )
    rendered = expl.format_terminal_text()
    assert "Routing for the last turn" in rendered
    assert "code-edit" in rendered
    assert "below agent quality floor" in rendered
    assert "claude-sonnet-4-5" in rendered
