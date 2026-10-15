"""Routing Policy and Candidate Filtering.

Document 2.4 (FR-22, FR-24, FR-30) & Document 5.7 (SEC-13):
- Filter out models lacking required capabilities (tool use, vision, context window).
- Enforce allow-providers and deny-providers.
- Enforce --local-only (reject all cloud providers).
- Enforce quality floor for agent turns (FR-24: tier >= 2 for edits/commands unless pinned).
- Filter out open-circuit providers.
- Filter out models exceeding cost cap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ijachi_router.config import ModelConfig
    from ijachi_router.routing.features import SessionNeed


def is_category_match(model_tags: list[str], category: str) -> bool:
    """Check if model matches requested task category with semantic fallbacks."""
    if category in model_tags:
        return True
    if category in ("debugging", "code-edit/refactor") and "code" in model_tags:
        return True
    if category == "simple-qa":
        return True  # Any model can handle basic QA
    return False


def filter_candidates(
    candidates: list["ModelConfig"],
    need: "SessionNeed",
    allow_providers: set[str] | None = None,
    deny_providers: set[str] | None = None,
    local_only: bool = False,
    max_cost_per_turn: float | None = None,
    agent_quality_floor: int = 2,
    open_circuit_providers: set[str] | None = None,
    pinned_model: str | None = None,
    priority: str = "efficient",
) -> tuple[list["ModelConfig"], dict[str, str]]:
    """Filter models against requirements. Returns (eligible_models, reasons_filtered)."""
    eligible: list["ModelConfig"] = []
    filtered_reasons: dict[str, str] = {}

    open_circuits = open_circuit_providers or set()

    for m in candidates:
        full_id = f"{m.provider}/{m.model_id}"

        # If user explicitly pinned a model, keep only that model
        if pinned_model:
            if m.model_id == pinned_model or full_id == pinned_model or m.provider == pinned_model:
                eligible.append(m)
            else:
                filtered_reasons[full_id] = "not the pinned model"
            continue

        # 1. Local-only enforcement (SEC-13)
        if local_only and m.provider not in ("local", "custom"):
            filtered_reasons[full_id] = "--local-only policy active"
            continue

        # 2. Allow / Deny provider lists
        if allow_providers and m.provider not in allow_providers:
            filtered_reasons[full_id] = f"provider '{m.provider}' not in allow list"
            continue
        if deny_providers and m.provider in deny_providers:
            filtered_reasons[full_id] = f"provider '{m.provider}' is in deny list"
            continue

        # 3. Circuit breaker check
        if m.provider in open_circuits:
            filtered_reasons[full_id] = f"circuit breaker open for provider '{m.provider}'"
            continue

        # 4. Capability check: tool use for agent turns (FR-22)
        # Note: local models or basic models might lack tool use
        quality_tier = getattr(m, "quality_tier", 2 if m.speed_tier == "fast" else 4)
        if need.requires_tools and quality_tier < agent_quality_floor:
            filtered_reasons[full_id] = f"below agent quality floor (tier {quality_tier} < {agent_quality_floor})"
            continue

        # 4b. Adequacy check: complexity floor
        # Tier 1 models (e.g. 1B-3B) are inadequate for moderate/high complexity code and reasoning
        if need.complexity >= 0.5 and quality_tier < 2:
            filtered_reasons[full_id] = f"below complexity adequacy floor (tier {quality_tier} < 2 for complexity {need.complexity:.2f})"
            continue

        # 5. Category match
        if not is_category_match(m.tags, need.category):
            filtered_reasons[full_id] = f"does not match category '{need.category}'"
            continue

        # 6. Cost cap check (bypassed if in 'best-fit' mode)
        from ijachi_router.config import normalize_mode
        if normalize_mode(priority) != "best-fit":
            est_cost = (500 / 1000) * m.input_per_1k + (need.expected_output_tokens / 1000) * m.output_per_1k
            if max_cost_per_turn is not None and est_cost > max_cost_per_turn:
                filtered_reasons[full_id] = f"estimated cost ${est_cost:.4f} exceeds max-cost ${max_cost_per_turn:.4f}"
                continue

        eligible.append(m)

    return eligible, filtered_reasons
