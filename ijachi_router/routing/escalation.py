"""Model Escalation and De-escalation manager.

Document 2.4 (FR-26):
Escalation shall trigger on:
- two consecutive tool errors
- a failing test after an edit attempt twice
- user retry or negative feedback
- loop detection (repetition)
- malformed output
De-escalation shall occur after a configurable run of successful easy turns.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EscalationDecision:
    escalate: bool
    reason: str = ""
    override_priority: str | None = None  # e.g., "quality"


class EscalationTracker:
    """Tracks turn outcomes and determines when to escalate to frontier models."""

    def __init__(self, deescalate_threshold: int = 4):
        self.consecutive_tool_errors: int = 0
        self.consecutive_test_failures: int = 0
        self.consecutive_easy_successes: int = 0
        self.deescalate_threshold = deescalate_threshold
        self.is_escalated: bool = False

    def record_tool_error(self, error: str = "") -> EscalationDecision:
        self.consecutive_tool_errors += 1
        self.consecutive_easy_successes = 0
        if self.consecutive_tool_errors >= 2:
            self.is_escalated = True
            return EscalationDecision(
                escalate=True,
                reason=f"{self.consecutive_tool_errors} consecutive tool errors ({error})" if error else f"{self.consecutive_tool_errors} consecutive tool errors",
                override_priority="quality",
            )
        return EscalationDecision(escalate=False)

    @property
    def required_quality_floor(self) -> str:
        return "high_reasoning" if self.is_escalated else "standard"

    def record_test_failure_after_edit(self) -> EscalationDecision:
        self.consecutive_test_failures += 1
        self.consecutive_easy_successes = 0
        if self.consecutive_test_failures >= 2:
            self.is_escalated = True
            return EscalationDecision(
                escalate=True,
                reason="two failed test repair attempts after edits",
                override_priority="quality",
            )
        return EscalationDecision(escalate=False)

    def record_success(self, complexity: float = 0.3) -> None:
        self.consecutive_tool_errors = 0
        self.consecutive_test_failures = 0
        if complexity < 0.5:
            self.consecutive_easy_successes += 1
            if self.is_escalated and self.consecutive_easy_successes >= self.deescalate_threshold:
                # De-escalate back to normal
                self.is_escalated = False
        else:
            self.consecutive_easy_successes = 0
