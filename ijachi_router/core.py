"""Core routing logic — ties classifier, config, optimizer, fallback, metrics.

Flow
----
1. ``classify`` prompt → (category, confidence, complexity)
2. ``score_models`` → ranked candidate list (category match + priority weights)
3. For the top candidate: ``optimize_prompt``
4. Build Provider instances for the ranked list
5. ``route_with_fallback`` → GenerationResult
6. ``log_result`` for metrics
7. Return result
"""

from __future__ import annotations

from pathlib import Path

from ijachi_router.classifier import complexity_score, predict_category
from ijachi_router.config import ModelConfig, RouterConfig, load_config
from ijachi_router.fallback import reset_breakers, route_with_fallback
from ijachi_router.humanizer import humanize
from ijachi_router.metrics import log_result
from ijachi_router.optimizer import optimize_prompt
from ijachi_router.providers import REGISTRY
from ijachi_router.providers.base import GenerationResult, Provider, ProviderError
from ijachi_router.security import scan_and_fix


# ---------------------------------------------------------------------------
# Model scoring
# ---------------------------------------------------------------------------

_SPEED_TIER_ORDER = {"fast": 0, "medium": 1, "slow": 2}


def _score_model(
    model: ModelConfig,
    category: str,
    complexity: float,
    priority: str,
    max_cost: float | None,
) -> float | None:
    """Return a numeric score for *model* (higher = preferred), or None to skip.

    Returns None if the model is disqualified (wrong category or cost cap hit).
    """
    # Category match is required
    if category not in model.tags:
        # Fallback: any model can handle simple-qa even if not tagged
        if category != "simple-qa":
            return None

    # Cost cap check (rough estimate: assume 500 tokens in + 500 out)
    estimated_cost = (500 / 1000) * model.input_per_1k + (500 / 1000) * model.output_per_1k
    if max_cost is not None and estimated_cost > max_cost:
        return None

    # Base score per priority
    if priority == "cost":
        # Lower cost → higher score
        cost_score = 1.0 / (estimated_cost + 1e-6)
        speed_score = 1.0 - _SPEED_TIER_ORDER[model.speed_tier] / 3.0
        quality_score = 1.0 if model.speed_tier == "slow" else 0.5
        score = 0.7 * cost_score + 0.2 * speed_score + 0.1 * quality_score

    elif priority == "speed":
        speed_score = 1.0 - _SPEED_TIER_ORDER[model.speed_tier] / 3.0
        cost_score = 1.0 / (estimated_cost + 1e-6)
        score = 0.7 * speed_score + 0.2 * cost_score + 0.1

    elif priority == "quality":
        quality_score = _SPEED_TIER_ORDER[model.speed_tier] / 2.0  # slow=best
        # For complex prompts, prefer slow/strong models even more
        complexity_bonus = complexity * 0.3
        score = quality_score + complexity_bonus

    else:  # balanced
        # Weight cost-efficiency, speed, and quality equally, biased by complexity
        tier = _SPEED_TIER_ORDER[model.speed_tier]
        if complexity > 0.6:
            # Complex prompt → prefer stronger (slower) models
            score = (tier + 1) * 0.5 + (1.0 / (estimated_cost + 1e-3)) * 0.1
        else:
            # Simple prompt → prefer cheap+fast
            cost_score = 1.0 / (estimated_cost + 1e-6)
            score = cost_score * 0.5 + (1.0 - tier / 3.0) * 0.5

    return score


def _rank_models(
    config: RouterConfig,
    category: str,
    complexity: float,
) -> list[ModelConfig]:
    """Return available models sorted by score, best first."""
    scored: list[tuple[float, ModelConfig]] = []
    for model in config.available_models():
        s = _score_model(
            model,
            category,
            complexity,
            config.priority,
            config.max_cost_per_call,
        )
        if s is not None:
            scored.append((s, model))

    # Sort descending by score, then alphabetically by model_id for stability
    scored.sort(key=lambda t: (-t[0], t[1].model_id))
    return [m for _, m in scored]


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

def _build_provider(model: ModelConfig) -> Provider:
    cls = REGISTRY[model.provider]
    return cls(model_id=model.model_id, pricing=model.pricing)


# ---------------------------------------------------------------------------
# Router class
# ---------------------------------------------------------------------------

class Router:
    """Main router — combines all subsystems."""

    def __init__(self, models_yaml: str | Path | None = None):
        self.config: RouterConfig = load_config(models_yaml)

    def reload(self) -> None:
        """Reload config from disk (useful after editing models.yaml)."""
        self.config = load_config()

    def route(self, prompt: str, humanize_mode: str = "light", **kwargs) -> GenerationResult:
        """Route *prompt* to the best available model and return the result.

        Args:
            prompt: The raw user prompt.
            humanize_mode: ``'light'`` (default), ``'full'``, or ``'off'``.
                - ``light``: Strip AI openers, closers, attribution watermarks, typography artifacts.
                - ``full``: All of light + code boilerplate comments + prose hedging.
                - ``off``: Return raw LLM output unchanged.
            **kwargs: Forwarded to the provider (e.g. ``max_tokens``).

        Returns:
            GenerationResult with text, model, cost, latency, token counts.

        Raises:
            ProviderError: If every candidate model fails.
            RuntimeError:  If no models are available (no API keys configured).
        """
        # 1. Classify
        category, confidence = predict_category(prompt)
        cx = complexity_score(prompt)

        # 2. Rank candidates
        ranked = _rank_models(self.config, category, cx)

        if not ranked:
            # Fallback: try all available models regardless of category
            ranked = list(self.config.available_models())

        if not ranked:
            raise ProviderError(
                "No providers available. Set at least one of: "
                "ANTHROPIC_API_KEY, OPENAI_API_KEY, or run Ollama locally."
            )

        # 3. Optimize prompt for the top candidate
        top_model = ranked[0]
        optimized = optimize_prompt(prompt, top_model.provider, category)

        # 4. Build provider instances
        providers = []
        for m in ranked:
            try:
                providers.append(_build_provider(m))
            except (KeyError, Exception):
                continue

        # 5. Route with fallback
        result = route_with_fallback(providers, optimized, **kwargs)

        # 6. Humanize: strip AI watermarks & artifacts using the requested mode
        clean_text = humanize(result.text, mode=humanize_mode)

        # 7. Security scan & auto-remediate any vulnerabilities in generated code
        clean_text, _ = scan_and_fix(clean_text)

        # Rebuild result with cleaned text (immutable dataclass - recreate)
        from dataclasses import replace as dc_replace
        result = dc_replace(result, text=clean_text)

        # 8. Log
        log_result(result)

        return result


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

def route(prompt: str, humanize_mode: str = "light", **kwargs) -> GenerationResult:
    """Convenience function: ``Router().route(prompt, humanize_mode=...)``."""  
    return Router().route(prompt, humanize_mode=humanize_mode, **kwargs)
