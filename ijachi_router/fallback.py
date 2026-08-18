"""Circuit-breaker fallback logic for multi-provider routing.

CircuitBreaker
--------------
Tracks failures in a rolling time window per provider. After ``threshold``
failures it "opens" (marks provider unavailable) for ``cooldown_s`` seconds.
After the cooldown it enters "half-open" and allows one trial request; if that
succeeds it resets; if it fails it re-opens.

route_with_fallback
-------------------
Tries providers in order, catching ProviderError, until one succeeds or all
are exhausted, at which point it re-raises the last error.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ijachi_router.providers.base import GenerationResult, ProviderError

if TYPE_CHECKING:
    from ijachi_router.providers.base import Provider


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------

@dataclass
class CircuitBreaker:
    """Per-provider circuit breaker using a rolling failure window."""

    provider_name: str
    threshold: int = 3          # failures before opening
    window_s: float = 60.0      # rolling window in seconds
    cooldown_s: float = 30.0    # open → half-open wait

    # Internal state
    _failures: deque = field(default_factory=deque, init=False, repr=False)
    _opened_at: float | None = field(default=None, init=False, repr=False)
    _half_open: bool = field(default=False, init=False, repr=False)

    def __post_init__(self):
        self._failures = deque()

    # -- State queries -------------------------------------------------------

    @property
    def is_open(self) -> bool:
        """True when the circuit is open (provider should be skipped)."""
        if self._opened_at is None:
            return False
        elapsed = time.monotonic() - self._opened_at
        if elapsed >= self.cooldown_s:
            # Transition to half-open
            self._half_open = True
            return False  # allow one trial
        return True

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self.is_open:
            return "open"
        return "half-open"

    # -- Lifecycle -----------------------------------------------------------

    def record_failure(self) -> None:
        """Record a provider failure; open the circuit if threshold exceeded."""
        now = time.monotonic()
        self._failures.append(now)
        # Evict stale failures outside the rolling window
        while self._failures and now - self._failures[0] > self.window_s:
            self._failures.popleft()
        if len(self._failures) >= self.threshold:
            self._opened_at = now
            self._half_open = False

    def record_success(self) -> None:
        """A successful call resets the breaker to closed."""
        self._failures.clear()
        self._opened_at = None
        self._half_open = False

    def allow_request(self) -> bool:
        """Return True if a request should be allowed through."""
        if self.is_open:
            return False  # circuit is open → skip
        # half-open: we already cleared is_open, allow the single trial
        return True


# ---------------------------------------------------------------------------
# Global registry of circuit breakers (one per provider name)
# ---------------------------------------------------------------------------

_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(provider_name: str, **kwargs) -> CircuitBreaker:
    """Return (creating if needed) the CircuitBreaker for *provider_name*."""
    if provider_name not in _breakers:
        _breakers[provider_name] = CircuitBreaker(provider_name, **kwargs)
    return _breakers[provider_name]


def reset_breakers() -> None:
    """Reset all circuit breakers — useful for testing."""
    _breakers.clear()


# ---------------------------------------------------------------------------
# route_with_fallback
# ---------------------------------------------------------------------------

def route_with_fallback(
    candidates: list["Provider"],
    prompt: str,
    **kwargs,
) -> GenerationResult:
    """Try each candidate provider in order, falling back on ProviderError.

    Args:
        candidates: Ordered list of Provider instances to try.
        prompt:     The (possibly optimized) prompt string.
        **kwargs:   Forwarded to ``provider.generate()``.

    Returns:
        The first successful GenerationResult.

    Raises:
        ProviderError: If every candidate fails (message includes all errors).
    """
    errors: list[str] = []

    for provider in candidates:
        breaker = get_breaker(provider.name)

        if not breaker.allow_request():
            errors.append(f"{provider.name}: circuit open (skipped)")
            continue

        try:
            result = provider.generate(prompt, **kwargs)
            breaker.record_success()
            return result
        except ProviderError as exc:
            breaker.record_failure()
            errors.append(str(exc))
            continue

    if not errors:
        raise ProviderError("No providers available (all circuits open or list empty)")
    raise ProviderError("All candidates failed:\n  " + "\n  ".join(errors))
