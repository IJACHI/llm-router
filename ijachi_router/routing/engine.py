"""Single routing engine shared by the one-shot router (core.Router / ijr / server / consensus)
and the coding assistant (AgentSessionLoop).

    rank_models(config, need, priority, ...) -> RankingResult

Steps: policy + capability filtering (routing.policy) -> category relaxation when nothing is
tagged for the request -> scoring (routing.scorer) -> stable ordering.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from ijachi_router.routing.features import SessionNeed
from ijachi_router.routing.policy import filter_candidates
from ijachi_router.routing.scorer import score_candidate

if TYPE_CHECKING:
    from ijachi_router.config import ModelConfig, RouterConfig


class NoEligibleModelError(Exception):
    """No configured model satisfies the request's policy constraints."""


@dataclass
class RankedCandidate:
    model: "ModelConfig"
    score: float
    est_cost: float


@dataclass
class RankingResult:
    ranked: list[RankedCandidate]
    filtered_reasons: dict[str, str] = field(default_factory=dict)
    category_relaxed: bool = False

    @property
    def models(self) -> list["ModelConfig"]:
        return [c.model for c in self.ranked]


def estimate_cost(model: "ModelConfig", input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1000) * model.input_per_1k + (output_tokens / 1000) * model.output_per_1k


def simple_need(category: str, confidence: float, complexity: float, requires_tools: bool = False) -> SessionNeed:
    """Need for a stateless one-shot request (no session/working set)."""
    return SessionNeed(
        category=category,
        confidence=confidence,
        complexity=complexity,
        requires_tools=requires_tools,
        expected_output_tokens=1000 if complexity < 0.5 else 3000,
    )


def rank_models(
    config: "RouterConfig",
    need: SessionNeed,
    priority: str | None = None,
    *,
    allow_providers: set[str] | None = None,
    deny_providers: set[str] | None = None,
    local_only: bool = False,
    max_cost_per_turn: float | None = None,
    pinned_model: str | None = None,
    current_model: str = "",
    cached_tokens: int = 0,
    input_tokens: int = 1000,
    quality_floor: int = 2,
    exclude_models: set[str] | frozenset[str] = frozenset(),
    open_circuit_providers: set[str] | None = None,
) -> RankingResult:
    """Return every usable model for *need*, best first.

    Raises NoEligibleModelError when a hard constraint (pinned model, local-only, allow list)
    leaves nothing; otherwise falls back progressively (category, then cost/quality floors)
    but never past the provider policy.
    """
    from ijachi_router.fallback import get_circuit_breaker

    priority = priority or config.priority
    candidates = [m for m in config.available_models() if m.model_id not in exclude_models]
    if open_circuit_providers is None:
        open_circuit_providers = {m.provider for m in candidates if get_circuit_breaker(m.provider).is_open}

    def _filter(n: SessionNeed, cost_cap: float | None, floor: int):
        return filter_candidates(
            candidates=candidates,
            need=n,
            allow_providers=allow_providers,
            deny_providers=deny_providers,
            local_only=local_only,
            max_cost_per_turn=cost_cap,
            agent_quality_floor=floor,
            open_circuit_providers=open_circuit_providers,
            pinned_model=pinned_model,
            priority=priority,
        )

    eligible, reasons = _filter(need, max_cost_per_turn, quality_floor)
    relaxed = False
    if not eligible and not pinned_model:
        # Nothing tagged for this category: relax the category only.
        eligible, _ = _filter(replace(need, category="simple-qa"), max_cost_per_turn, quality_floor)
        relaxed = bool(eligible)
    if not eligible and not pinned_model and max_cost_per_turn is None:
        # Last resort: ignore the agent quality floor (still honouring provider policy).
        eligible, _ = _filter(replace(need, category="simple-qa", requires_tools=False, complexity=0.0), None, 0)
        relaxed = bool(eligible)

    if not eligible:
        if pinned_model:
            raise NoEligibleModelError(
                f"Pinned model '{pinned_model}' is not available "
                "(missing API key, not pulled in Ollama, or filtered by provider policy). "
                "Use /model auto to restore routing."
            )
        if local_only or allow_providers:
            raise NoEligibleModelError(
                "No model satisfies the provider policy (--local-only / --allow-providers). "
                "Start Ollama, pull a model, or relax the policy."
            )
        if max_cost_per_turn is not None:
            raise NoEligibleModelError(f"No model fits the cost cap of ${max_cost_per_turn:.4f} per request.")
        raise NoEligibleModelError(
            "No providers available. Set an API key (e.g. ANTHROPIC_API_KEY, OPENAI_API_KEY) or start Ollama."
        )

    ranked: list[RankedCandidate] = []
    for m in eligible:
        s = score_candidate(
            model=m,
            need=need,
            priority=priority,
            input_tokens=input_tokens,
            is_current_model=bool(current_model) and m.model_id == current_model,
            cached_tokens=cached_tokens,
        )
        ranked.append(RankedCandidate(m, s, estimate_cost(m, input_tokens, need.expected_output_tokens)))
    ranked.sort(key=lambda c: (-c.score, c.est_cost, c.model.model_id))
    return RankingResult(ranked=ranked, filtered_reasons=reasons, category_relaxed=relaxed)
