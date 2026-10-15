"""Feature extraction for session-aware routing.

Document 2.4 (FR-20):
Routing runs per model request using the prompt AND session state:
recent categories, whether tool results are pending, files in play,
prior failures, current model, and remaining budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ijachi_router.session.state import SessionState


@dataclass
class SessionNeed:
    category: str = "general"
    confidence: float = 1.0
    complexity: float = 0.5
    requires_tools: bool = False
    requires_vision: bool = False
    expected_output_tokens: int = 500
    files_in_play: list[str] = field(default_factory=list)
    has_prior_failures: bool = False
    current_model: str = ""
    remaining_budget_usd: float | None = None


def extract_session_need(
    prompt: str,
    state: "SessionState",
    category: str,
    confidence: float,
    complexity: float,
) -> SessionNeed:
    """Combine prompt classification with session state to build a rich routing Need."""
    lower = prompt.lower()
    tool_keywords = [
        "file", "read", "write", "edit", "run", "test", "mkdir", "git",
        "search", "grep", "fix", "find", "list", "install", "check",
        "build", "create", "scaffold", "generate", "make", "develop",
        "website", "app", "application", "newsletter", "implement", "pipeline",
    ]
    requires_tools = any(kw in lower for kw in tool_keywords) or bool(state.working_set)
    requires_vision = any(ext in lower for ext in [".png", ".jpg", ".jpeg", ".webp", ".svg", "screenshot", "image"])

    files_in_play = list(state.working_set.keys())
    has_prior_failures = state.consecutive_tool_failures > 0

    remaining_budget = None
    if state.budget_usd is not None:
        remaining_budget = max(0.0, state.budget_usd - state.total_cost_usd)

    return SessionNeed(
        category=category,
        confidence=confidence,
        complexity=complexity,
        requires_tools=requires_tools,
        requires_vision=requires_vision,
        expected_output_tokens=1000 if complexity < 0.5 else 3000,
        files_in_play=files_in_play,
        has_prior_failures=has_prior_failures,
        current_model=state.current_model,
        remaining_budget_usd=remaining_budget,
    )
