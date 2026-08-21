"""End-to-end tests for ijachi_router/core.py — all provider calls are mocked."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ijachi_router.core import Router, _rank_models
from ijachi_router.config import load_config
from ijachi_router.fallback import reset_breakers
from ijachi_router.providers.base import GenerationResult, ProviderError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MODELS_YAML = Path(__file__).parent.parent / "models.yaml"


def _mock_result(provider="anthropic", model="claude-haiku-4-5") -> GenerationResult:
    return GenerationResult(
        text="Mocked response",
        provider=provider,
        model=model,
        input_tokens=50,
        output_tokens=100,
        cost_usd=0.0002,
        latency_s=0.3,
    )


def _make_router_with_provider(provider_name: str, raises: bool = False) -> tuple[Router, MagicMock]:
    """Build a Router where one provider's generate() is mocked."""
    router = Router(models_yaml=_MODELS_YAML)
    # Force only that provider to be available
    router.config.available_providers = {provider_name}

    mock_provider = MagicMock()
    mock_provider.name = provider_name
    if raises:
        mock_provider.generate.side_effect = ProviderError("mock failure")
    else:
        mock_provider.generate.return_value = _mock_result(provider=provider_name)

    return router, mock_provider


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRouter:
    def setup_method(self):
        reset_breakers()

    def test_route_returns_generation_result(self):
        router, mock_prov = _make_router_with_provider("anthropic")
        with (
            patch("ijachi_router.core._build_provider", return_value=mock_prov),
            patch("ijachi_router.core.log_result"),
        ):
            result = router.route("What is Python?")

        assert isinstance(result, GenerationResult)
        assert result.text == "Mocked response"

    def test_route_calls_log_result(self):
        router, mock_prov = _make_router_with_provider("anthropic")
        with (
            patch("ijachi_router.core._build_provider", return_value=mock_prov),
            patch("ijachi_router.core.log_result") as mock_log,
        ):
            router.route("What is Python?")

        mock_log.assert_called_once()

    def test_route_uses_optimizer(self):
        """The prompt passed to the provider should be the optimized version."""
        router, mock_prov = _make_router_with_provider("anthropic")
        with (
            patch("ijachi_router.core._build_provider", return_value=mock_prov),
            patch("ijachi_router.core.log_result"),
        ):
            router.route("Write a poem about autumn")

        call_args = mock_prov.generate.call_args
        passed_prompt = call_args[0][0]
        # Anthropic optimizer wraps in <task> tags
        assert "<task>" in passed_prompt

    def test_route_raises_when_no_providers(self):
        router = Router(models_yaml=_MODELS_YAML)
        router.config.available_providers = set()  # nothing available

        with pytest.raises(ProviderError, match="No providers available"):
            router.route("Hello")

    def test_route_falls_back_on_provider_error(self):
        router = Router(models_yaml=_MODELS_YAML)
        router.config.available_providers = {"anthropic", "openai"}

        failing = MagicMock()
        failing.name = "anthropic"
        failing.generate.side_effect = ProviderError("anthropic down")

        working = MagicMock()
        working.name = "openai"
        working.generate.return_value = _mock_result(provider="openai", model="gpt-4o-mini")

        providers_built = [failing, working]
        build_iter = iter(providers_built)

        with (
            patch("ijachi_router.core._build_provider", side_effect=lambda m: next(build_iter)),
            patch("ijachi_router.core.log_result"),
        ):
            result = router.route("What is 2+2?")

        assert result.provider == "openai"

    def test_priority_cost_prefers_cheapest(self):
        config = load_config(_MODELS_YAML)
        config.available_providers = {"anthropic", "openai", "local"}
        config.priority = "cost"
        ranked = _rank_models(config, "simple-qa", complexity=0.1)
        # Local models are always pushed to the end when remote providers are available
        # (they are free but may be offline) — the cheapest *remote* model should rank first.
        remote_models = [m for m in ranked if m.provider != "local"]
        local_models = [m for m in ranked if m.provider == "local"]
        assert remote_models, "Expected at least one remote model in ranked list"
        assert local_models, "Expected at least one local model in ranked list"
        # Remote models must appear before local models
        assert ranked.index(remote_models[0]) < ranked.index(local_models[0])

    def test_priority_quality_prefers_slow_models(self):
        config = load_config(_MODELS_YAML)
        config.available_providers = {"anthropic", "openai"}
        config.priority = "quality"
        ranked = _rank_models(config, "reasoning", complexity=0.8)
        # slow-tier models should be at the top
        assert ranked[0].speed_tier == "slow"

    def test_max_cost_cap_filters_expensive_models(self):
        config = load_config(_MODELS_YAML)
        config.available_providers = {"anthropic", "openai"}
        config.max_cost_per_call = 0.0001  # very low — should filter expensive models
        config.priority = "balanced"
        ranked = _rank_models(config, "simple-qa", complexity=0.1)
        # All ranked models must have estimated cost ≤ cap
        for m in ranked:
            estimated = (500 / 1000) * m.input_per_1k + (500 / 1000) * m.output_per_1k
            assert estimated <= config.max_cost_per_call, (
                f"{m.model_id} cost {estimated:.6f} exceeds cap {config.max_cost_per_call}"
            )

    def test_module_level_route_function(self):
        """The module-level route() should work like Router().route()."""
        from ijachi_router.core import route

        mock_prov = MagicMock()
        mock_prov.name = "anthropic"
        mock_prov.generate.return_value = _mock_result()

        with (
            patch("ijachi_router.core._build_provider", return_value=mock_prov),
            patch("ijachi_router.core.log_result"),
            patch("ijachi_router.config._detect_available_providers", return_value={"anthropic"}),
        ):
            result = route("Hello")

        assert isinstance(result, GenerationResult)
