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
    """Return available models sorted by score, best first.

    Local (Ollama) models are deprioritized when remote providers are also
    available — they are free but may be offline, so they are only tried as
    a last resort unless no remote providers are configured.
    """
    scored: list[tuple[float, ModelConfig]] = []
    has_remote = any(
        m.provider != "local" and m.provider in config.available_providers
        for m in config.models
    )
    for model in config.available_models():
        s = _score_model(
            model,
            category,
            complexity,
            config.priority,
            config.max_cost_per_call,
        )
        if s is not None:
            # If remote providers are available, push local models to the very end.
            # Use a fixed sentinel (-1.0) because zero-cost local models score
            # astronomically high in cost-based scoring (1/1e-6 = 1,000,000),
            # so a simple -1000 offset isn't enough to push them below remote models.
            if has_remote and model.provider == "local":
                s = -1.0
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

    def route(
        self,
        prompt: str,
        humanize_mode: str = "light",
        _classify_as: str | None = None,
        priority: str | None = None,
        force_model: str | None = None,
        **kwargs,
    ) -> GenerationResult:
        """Route *prompt* to the best available model and return the result.

        Args:
            prompt: The raw user prompt (full context sent to the LLM).
            humanize_mode: ``'light'`` (default), ``'full'``, or ``'off'``.
            _classify_as: Optional short text used *only* for classification/routing.
            priority: Optional override for routing priority (cost, speed, quality, balanced).
            force_model: Optional specific model_id to pin and use directly.
            **kwargs: Forwarded to the provider.
        """
        # 0. If a specific model is forced, locate and rank it first
        if force_model:
            matching = [m for m in self.config.models if m.model_id == force_model or force_model.lower() in m.model_id.lower()]
            if matching:
                ranked = matching
            else:
                ranked = list(self.config.available_models())
        else:
            # 1. Classify — use _classify_as if provided, else fall back to full prompt
            classify_text = _classify_as if _classify_as else prompt
            category, confidence = predict_category(classify_text)
            cx = complexity_score(classify_text)

            # 2. Rank candidates with optional priority override
            effective_config = self.config
            if priority:
                from dataclasses import replace as dc_replace
                effective_config = dc_replace(self.config, priority=priority)

            ranked = _rank_models(effective_config, category, cx)

            if not ranked:
                # Fallback: try all available models regardless of category
                ranked = list(self.config.available_models())

        if not ranked:
            raise ProviderError(
                "No providers available. Configure at least one provider with:\n"
                "  ijachi keys set <provider> <key>\n"
                "Available providers: gemini, openai, anthropic, groq, deepseek, moonshot\n"
                "Or run Ollama locally for a free offline option."
            )

        from ijachi_router.ui import status_spinner

        with status_spinner(f"Analyzing prompt & ranking optimal models...") as spinner:
            # 3. Optimize prompt for the top candidate
            top_model = ranked[0]
            category = category if not force_model else "code"
            optimized = optimize_prompt(prompt, top_model.provider, category)

            # 4. Build provider instances
            providers = []
            for m in ranked:
                try:
                    providers.append(_build_provider(m))
                except (KeyError, Exception):
                    continue

            # Update status with target model
            spinner.update(f"Querying {top_model.provider}/{top_model.model_id}...")

            # 5. Route with fallback
            result = route_with_fallback(providers, optimized, **kwargs)

            spinner.update("Auditing security & formatting output...")
            # 6. Humanize: strip AI watermarks & artifacts using the requested mode
            clean_text = humanize(result.text, mode=humanize_mode)

            # 7. Security scan & auto-remediate any vulnerabilities in generated code
            clean_text, _ = scan_and_fix(clean_text)

        # 8. Compute Telemetry & Cost Savings (Baseline: GPT-4o frontier standard)
        baseline_model_id = "gpt-4o"
        baseline_cost_usd = (result.input_tokens / 1000.0) * 0.005 + (result.output_tokens / 1000.0) * 0.015
        cost_saved_usd = max(0.0, baseline_cost_usd - result.cost_usd)
        savings_pct = (cost_saved_usd / baseline_cost_usd * 100.0) if baseline_cost_usd > 0 else 0.0
        tok_sec = (result.input_tokens + result.output_tokens) / result.latency_s if result.latency_s > 0 else 0.0

        # Rebuild result with cleaned text and complete telemetry metrics
        from dataclasses import replace as dc_replace
        result = dc_replace(
            result,
            text=clean_text,
            category=category,
            complexity=cx if not force_model else 0.5,
            baseline_model=baseline_model_id,
            baseline_cost_usd=baseline_cost_usd,
            cost_saved_usd=cost_saved_usd,
            savings_pct=savings_pct,
            tokens_per_sec=tok_sec,
        )

        # 9. Log
        log_result(result)

        return result


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

def route(
    prompt: str,
    humanize_mode: str = "light",
    _classify_as: str | None = None,
    priority: str | None = None,
    force_model: str | None = None,
    **kwargs,
) -> GenerationResult:
    """Convenience function: ``Router().route(prompt, ...)``."""
    return Router().route(
        prompt,
        humanize_mode=humanize_mode,
        _classify_as=_classify_as,
        priority=priority,
        force_model=force_model,
        **kwargs,
    )
