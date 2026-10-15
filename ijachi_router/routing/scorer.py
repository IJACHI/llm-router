"""Candidate Model Scorer with model stickiness and token caching bonuses.

Document 2.4 (FR-23) & Document 3.6:
Combines category fit, complexity fit, priority weights, expected cost for assembled context,
latency tier, provider health, and a stickiness bonus for the current active model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ijachi_router.config import ModelConfig
    from ijachi_router.routing.features import SessionNeed

_SPEED_TIER_ORDER = {"fast": 0, "medium": 1, "slow": 2}


def score_candidate(
    model: "ModelConfig",
    need: "SessionNeed" | None = None,
    priority: str = "balanced",
    input_tokens: int = 500,
    is_current_model: bool = False,
    cached_tokens: int = 0,
    previous_model: str | None = None,
) -> float:
    """Return a composite score for candidate model (higher = better)."""
    if need is None:
        from ijachi_router.routing.features import SessionNeed
        need = SessionNeed(category="code", confidence=1.0, complexity=0.5, requires_tools=False, expected_output_tokens=500)

    if previous_model:
        if previous_model in (model.model_id, f"{model.provider}/{model.model_id}"):
            is_current_model = True

    # 1. Expected cost calculation based on assembled context token count
    in_tok = max(input_tokens, 500)
    out_tok = need.expected_output_tokens
    expected_cost = (in_tok / 1000) * model.input_per_1k + (out_tok / 1000) * model.output_per_1k

    speed_rank = _SPEED_TIER_ORDER.get(model.speed_tier, 1)
    speed_score = 1.0 - (speed_rank / 3.0)

    # Base quality estimation utilizing model.quality_tier (1 to 4)
    tier = getattr(model, "quality_tier", 2)
    quality_score = tier / 4.0
    if need.complexity > 0.6:
        quality_score += (tier / 4.0) * (need.complexity * 0.5)

    # Normalized cost score [0, 1] where $0.00 = 1.0
    cost_score = 1.0 / (1.0 + expected_cost * 100.0)

    # 2. Priority weighting
    if priority == "cost":
        base_score = 0.70 * cost_score + 0.15 * speed_score + 0.15 * quality_score

    elif priority == "speed":
        base_score = 0.65 * speed_score + 0.20 * cost_score + 0.15 * quality_score

    elif priority == "quality":
        base_score = 0.80 * quality_score + 0.10 * speed_score + 0.10 * cost_score

    else:  # balanced
        if need.complexity > 0.7:
            # Complex tasks demand high quality; quality dominates cost
            base_score = 0.60 * quality_score + 0.25 * cost_score + 0.15 * speed_score
        elif need.complexity > 0.4:
            # Moderate complexity: balance quality and cost
            base_score = 0.45 * quality_score + 0.40 * cost_score + 0.15 * speed_score
        else:
            # Simple tasks: cost-efficiency and speed take precedence
            base_score = 0.55 * cost_score + 0.30 * speed_score + 0.15 * quality_score

    # 3. Model stickiness bonus (Document 3.6)
    # The current model receives a score bonus that grows with cached tokens to prevent thrashing
    stickiness_bonus = 0.0
    if is_current_model:
        # Cache benefit bonus
        cache_factor = min(cached_tokens / 10_000.0, 1.0)
        stickiness_bonus = 0.25 + (0.25 * cache_factor)

    return base_score + stickiness_bonus
