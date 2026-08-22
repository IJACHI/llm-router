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

import time
from pathlib import Path
from typing import Iterator

from ijachi_router.classifier import complexity_score, predict_category
from ijachi_router.config import ModelConfig, RouterConfig, load_config
from ijachi_router.fallback import reset_breakers, route_with_fallback
from ijachi_router.humanizer import humanize
from ijachi_router.live_events import emit
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
# Internal shared pipeline setup
# ---------------------------------------------------------------------------

def _prepare_pipeline(
    prompt: str,
    config: RouterConfig,
    _classify_as: str | None = None,
    priority: str | None = None,
    force_model: str | None = None,
) -> tuple[list[Provider], str, str, float]:
    """Classify, rank, and build providers. Returns (providers, optimized_prompt, category, complexity)."""
    category = "code"
    cx = 0.5

    if force_model:
        matching = [m for m in config.models if m.model_id == force_model or force_model.lower() in m.model_id.lower()]
        ranked = matching if matching else list(config.available_models())
    else:
        classify_text = _classify_as if _classify_as else prompt
        category, confidence = predict_category(classify_text)
        cx = complexity_score(classify_text)

        emit(
            "classify",
            f"Classified → [bold]{category}[/bold] · complexity {cx:.2f} · confidence {confidence:.2f}",
            category=category,
            complexity=cx,
            confidence=confidence,
        )

        effective_config = config
        if priority:
            from dataclasses import replace as dc_replace
            effective_config = dc_replace(config, priority=priority)

        ranked = _rank_models(effective_config, category, cx)
        if not ranked:
            ranked = list(config.available_models())

        if ranked:
            top3 = " · ".join(
                f"{m.provider}/{m.model_id}" for m in ranked[:3]
            )
            emit(
                "rank",
                f"Ranked {len(ranked)} model(s) → {top3}{'...' if len(ranked) > 3 else ''}",
                count=len(ranked),
            )

    if not ranked:
        raise ProviderError(
            "No providers available. Configure at least one provider with:\n"
            "  ijachi keys set <provider> <key>\n"
            "Available providers: gemini, openai, anthropic, groq, deepseek, moonshot\n"
            "Or run Ollama locally for a free offline option."
        )

    top_model = ranked[0]
    optimized = optimize_prompt(prompt, top_model.provider, category)

    providers = []
    for m in ranked:
        try:
            providers.append(_build_provider(m))
        except (KeyError, Exception):
            continue

    emit("query", f"Querying [bold]{top_model.provider}/{top_model.model_id}[/bold]...", model=f"{top_model.provider}/{top_model.model_id}")
    return providers, optimized, category, cx


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
        providers, optimized, category, cx = _prepare_pipeline(
            prompt, self.config, _classify_as, priority, force_model
        )

        # Route with fallback (uses speculative racing when priority=speed)
        effective_priority = priority or self.config.priority
        is_speed = (effective_priority == "speed")
        result = route_with_fallback(providers, optimized, speculative=is_speed, **kwargs)

        # Humanize and security scan
        emit("humanize", "Stripping AI watermarks & formatting output...")
        clean_text = humanize(result.text, mode=humanize_mode)
        emit("security", "Running security scan...")
        clean_text, _ = scan_and_fix(clean_text)

        # Compute telemetry
        baseline_cost_usd = (result.input_tokens / 1000.0) * 0.005 + (result.output_tokens / 1000.0) * 0.015
        cost_saved_usd = max(0.0, baseline_cost_usd - result.cost_usd)
        savings_pct = (cost_saved_usd / baseline_cost_usd * 100.0) if baseline_cost_usd > 0 else 0.0
        tok_sec = (result.input_tokens + result.output_tokens) / result.latency_s if result.latency_s > 0 else 0.0

        from dataclasses import replace as dc_replace
        result = dc_replace(
            result,
            text=clean_text,
            category=category,
            complexity=cx,
            baseline_model="gpt-4o",
            baseline_cost_usd=baseline_cost_usd,
            cost_saved_usd=cost_saved_usd,
            savings_pct=savings_pct,
            tokens_per_sec=tok_sec,
        )

        savings_str = f" · saved ${cost_saved_usd:.4f} ({savings_pct:.0f}% vs gpt-4o)" if cost_saved_usd > 0 else ""
        emit(
            "done",
            f"{result.total_tokens} tokens · ${result.cost_usd:.4f}{savings_str} · {result.latency_s:.2f}s",
            model=result.model,
            cost_usd=result.cost_usd,
            total_tokens=result.total_tokens,
        )

        log_result(result)
        return result

    def route_stream(
        self,
        prompt: str,
        humanize_mode: str = "light",
        _classify_as: str | None = None,
        priority: str | None = None,
        force_model: str | None = None,
        **kwargs,
    ) -> Iterator[str | GenerationResult]:
        """Stream *prompt* response token-by-token, emitting pipeline events live.

        Yields text chunks (``str``) from the provider as they arrive, then
        yields a final :class:`GenerationResult` as the very last item so the
        caller can display the telemetry card.

        Args:
            prompt: The raw user prompt.
            humanize_mode: Post-processing humanize mode.
            _classify_as: Optional classification-only text.
            priority: Routing priority override.
            force_model: Pin a specific model.
            **kwargs: Forwarded to the provider streaming call.
        """
        providers, optimized, category, cx = _prepare_pipeline(
            prompt, self.config, _classify_as, priority, force_model
        )

        if not providers:
            raise ProviderError("No providers could be constructed.")

        # Stream from the top provider; fall back to generate() if streaming fails
        primary = providers[0]
        start = time.monotonic()
        full_text = ""

        try:
            for chunk in primary.stream(optimized, **kwargs):
                full_text += chunk
                yield chunk
        except Exception:
            # Streaming failed — fall back to non-streaming generate
            try:
                res = primary.generate(optimized, **kwargs)
                full_text = res.text
                yield full_text
            except Exception as e:
                # Try remaining fallback providers
                for fallback in providers[1:]:
                    try:
                        res = fallback.generate(optimized, **kwargs)
                        full_text = res.text
                        yield full_text
                        break
                    except Exception:
                        continue
                else:
                    raise ProviderError(f"All providers failed: {e}") from e

        latency = time.monotonic() - start

        # Post-process
        emit("humanize", "Stripping AI watermarks...")
        clean_text = humanize(full_text, mode=humanize_mode)
        emit("security", "Running security scan...")
        clean_text, _ = scan_and_fix(clean_text)

        # Estimate tokens (approximate from char count if streaming doesn't expose usage)
        approx_out = max(1, len(clean_text) // 4)
        approx_in = max(1, len(optimized) // 4)

        pricing = primary.pricing
        cost_usd = (approx_in / 1000) * pricing.get("input_per_1k", 0) + (approx_out / 1000) * pricing.get("output_per_1k", 0)
        baseline_cost_usd = (approx_in / 1000.0) * 0.005 + (approx_out / 1000.0) * 0.015
        cost_saved_usd = max(0.0, baseline_cost_usd - cost_usd)
        savings_pct = (cost_saved_usd / baseline_cost_usd * 100.0) if baseline_cost_usd > 0 else 0.0
        tok_sec = (approx_in + approx_out) / latency if latency > 0 else 0.0

        result = GenerationResult(
            text=clean_text,
            provider=primary.name,
            model=primary.model_id,
            input_tokens=approx_in,
            output_tokens=approx_out,
            cost_usd=round(cost_usd, 6),
            latency_s=round(latency, 3),
            category=category,
            complexity=cx,
            baseline_model="gpt-4o",
            baseline_cost_usd=round(baseline_cost_usd, 6),
            cost_saved_usd=round(cost_saved_usd, 6),
            savings_pct=round(savings_pct, 2),
            tokens_per_sec=round(tok_sec, 1),
        )

        savings_str = f" · saved ${cost_saved_usd:.4f} ({savings_pct:.0f}% vs gpt-4o)" if cost_saved_usd > 0 else ""
        emit(
            "done",
            f"~{result.total_tokens} tokens · ${result.cost_usd:.4f}{savings_str} · {latency:.2f}s",
            model=result.model,
            cost_usd=result.cost_usd,
            total_tokens=result.total_tokens,
        )

        log_result(result)

        # Final yield: the GenerationResult for the telemetry card
        yield result


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


def route_stream(
    prompt: str,
    humanize_mode: str = "light",
    _classify_as: str | None = None,
    priority: str | None = None,
    force_model: str | None = None,
    **kwargs,
) -> Iterator[str | GenerationResult]:
    """Convenience function: ``Router().route_stream(prompt, ...)``."""
    yield from Router().route_stream(
        prompt,
        humanize_mode=humanize_mode,
        _classify_as=_classify_as,
        priority=priority,
        force_model=force_model,
        **kwargs,
    )
