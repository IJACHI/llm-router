"""Core one-shot routing: classify -> rank (shared engine) -> optimize -> fallback -> log.

The same ranking engine (``routing.engine.rank_models``) drives the coding assistant, so a
prompt routed with ``ijr route`` and a turn in ``ijachi-code`` are scored identically.
"""

from __future__ import annotations

from pathlib import Path

from ijachi_router.config import ModelConfig, RouterConfig, load_config
from ijachi_router.fallback import reset_breakers, route_with_fallback  # noqa: F401 (re-export)
from ijachi_router.metrics import log_result
from ijachi_router.providers import REGISTRY
from ijachi_router.providers.base import GenerationResult, Provider, ProviderError
from ijachi_router.routing.classifier import complexity_score, predict_category
from ijachi_router.routing.engine import NoEligibleModelError, rank_models, simple_need


def _rank_models(
    config: RouterConfig,
    category: str,
    complexity: float,
    priority: str | None = None,
    exclude_models: set[str] | frozenset[str] = frozenset(),
) -> list[ModelConfig]:
    """Available models for a one-shot request, best first (empty if none qualify)."""
    try:
        result = rank_models(
            config,
            simple_need(category, 1.0, complexity),
            priority or config.priority,
            max_cost_per_turn=config.max_cost_per_call,
            quality_floor=0,
            exclude_models=exclude_models,
            input_tokens=500,
        )
    except NoEligibleModelError:
        return []
    return result.models


def _build_provider(model: ModelConfig) -> Provider:
    cls = REGISTRY[model.provider]
    return cls(model_id=model.model_id, pricing=model.pricing)


class Router:
    """Main router — combines all subsystems."""

    def __init__(self, models_yaml: str | Path | None = None):
        self.config: RouterConfig = load_config(models_yaml)

    def reload(self) -> None:
        """Reload config from disk (useful after editing models.yaml)."""
        self.config = load_config()

    def route(self, prompt: str, **kwargs) -> GenerationResult:
        """Route *prompt* to the best available model and return the result.

        Routing options (consumed here, never forwarded to providers):
            priority, max_cost, exclude_models
        Everything else (e.g. ``max_tokens``, ``system``) is forwarded to the provider.
        """
        priority = kwargs.pop("priority", None)
        max_cost = kwargs.pop("max_cost", None)
        exclude_models = frozenset(kwargs.pop("exclude_models", None) or ())

        category, _confidence = predict_category(prompt)
        cx = complexity_score(prompt)

        cfg = self.config
        if max_cost is not None:
            from dataclasses import replace as _dc_replace
            cfg = _dc_replace(cfg, max_cost_per_call=max_cost)
        ranked = _rank_models(cfg, category, cx, priority=priority, exclude_models=exclude_models)

        if not ranked:
            raise ProviderError(
                "No providers available. Set at least one of: "
                "ANTHROPIC_API_KEY, OPENAI_API_KEY, or run Ollama locally."
            )

        providers = []
        for m in ranked:
            try:
                providers.append(_build_provider(m))
            except Exception:
                continue

        result = route_with_fallback(providers, prompt, category=category, **kwargs)
        result.category = category
        log_result(result)
        return result


def route(prompt: str, **kwargs) -> GenerationResult:
    """Convenience function: ``Router().route(prompt)``."""
    return Router().route(prompt, **kwargs)
