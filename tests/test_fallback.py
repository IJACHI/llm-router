"""Tests for ijachi_router/fallback.py — circuit breaker + route_with_fallback."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from ijachi_router.fallback import (
    CircuitBreaker,
    get_breaker,
    reset_breakers,
    route_with_fallback,
)
from ijachi_router.providers.base import GenerationResult, ProviderError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_provider(name: str, raises: bool = False, result_text: str = "ok") -> MagicMock:
    """Build a mock Provider that either returns a result or raises ProviderError."""
    provider = MagicMock()
    provider.name = name
    if raises:
        provider.generate.side_effect = ProviderError(f"{name} failed")
    else:
        provider.generate.return_value = GenerationResult(
            text=result_text,
            provider=name,
            model="test-model",
            input_tokens=10,
            output_tokens=20,
            cost_usd=0.001,
            latency_s=0.5,
        )
    return provider


# ---------------------------------------------------------------------------
# CircuitBreaker unit tests
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    def setup_method(self):
        reset_breakers()

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker("test", threshold=3)
        assert cb.state == "closed"
        assert cb.is_open is False
        assert cb.allow_request() is True

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker("test", threshold=3, window_s=60)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "open"
        assert cb.is_open is True
        assert cb.allow_request() is False

    def test_does_not_open_before_threshold(self):
        cb = CircuitBreaker("test", threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"
        assert cb.allow_request() is True

    def test_success_resets_breaker(self):
        cb = CircuitBreaker("test", threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.is_open
        cb.record_success()
        assert cb.state == "closed"
        assert cb.allow_request() is True

    def test_cooldown_transitions_to_half_open(self):
        cb = CircuitBreaker("test", threshold=2, cooldown_s=0.05)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open
        time.sleep(0.1)
        # After cooldown, is_open should return False (half-open)
        assert cb.is_open is False
        assert cb.allow_request() is True

    def test_old_failures_evicted_from_window(self):
        cb = CircuitBreaker("test", threshold=3, window_s=0.05)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.1)
        # Old failures should have expired; this new one alone shouldn't trip
        cb.record_failure()
        assert cb.state == "closed"


# ---------------------------------------------------------------------------
# route_with_fallback tests
# ---------------------------------------------------------------------------

class TestRouteWithFallback:
    def setup_method(self):
        reset_breakers()

    def test_returns_first_success(self):
        p1 = _make_provider("p1")
        p2 = _make_provider("p2")
        result = route_with_fallback([p1, p2], "hello")
        assert result.text == "ok"
        p1.generate.assert_called_once()
        p2.generate.assert_not_called()

    def test_falls_back_on_provider_error(self):
        p1 = _make_provider("p1", raises=True)
        p2 = _make_provider("p2", result_text="fallback result")
        result = route_with_fallback([p1, p2], "hello")
        assert result.text == "fallback result"
        assert result.provider == "p2"

    def test_raises_when_all_fail(self):
        p1 = _make_provider("p1", raises=True)
        p2 = _make_provider("p2", raises=True)
        with pytest.raises(ProviderError):
            route_with_fallback([p1, p2], "hello")

    def test_raises_on_empty_list(self):
        with pytest.raises(ProviderError):
            route_with_fallback([], "hello")

    def test_circuit_opens_after_repeated_failures(self):
        """After threshold failures, the breaker opens and provider is skipped."""
        p1 = _make_provider("p1_circuit", raises=True)
        p2 = _make_provider("p2_circuit")

        breaker = get_breaker("p1_circuit", threshold=2)
        # Trigger two failures to open the circuit
        for _ in range(2):
            try:
                route_with_fallback([p1], "test")
            except ProviderError:
                pass

        assert breaker.is_open, "Circuit should be open after threshold failures"

        # Now route with both — p1 should be skipped, p2 should answer
        result = route_with_fallback([p1, p2], "hello")
        assert result.provider == "p2_circuit"
        # p1.generate was called only during the two failure runs, not in this call
        assert p1.generate.call_count == 2

    def test_skips_open_circuit_provider(self):
        p1 = _make_provider("open_circuit")
        breaker = get_breaker("open_circuit", threshold=1)
        breaker.record_failure()  # manually open

        p2 = _make_provider("healthy")
        result = route_with_fallback([p1, p2], "hello")
        p1.generate.assert_not_called()
        assert result.provider == "healthy"
