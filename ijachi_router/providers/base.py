"""Abstract provider interface. Every backend (OpenAI, Anthropic, local, ...)
implements this so the router core never has to know provider details."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator


@dataclass
class GenerationResult:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_s: float
    raw_error: str | None = None
    category: str = "general"
    complexity: float = 0.5
    cost_saved_usd: float = 0.0
    savings_pct: float = 0.0
    tokens_per_sec: float = 0.0
    baseline_model: str = "gpt-4o"
    baseline_cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ProviderError(Exception):
    """Raised when a provider call fails (timeout, auth, rate limit, etc)."""


class Provider(ABC):
    name: str = "base"

    def __init__(self, model_id: str, pricing: dict):
        self.model_id = model_id
        self.pricing = pricing  # {"input_per_1k": float, "output_per_1k": float}

    @abstractmethod
    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        """Return (text, input_tokens, output_tokens). Raise ProviderError on failure."""
        raise NotImplementedError

    def _stream(self, prompt: str, **kwargs) -> Iterator[str]:
        """Yield text chunks as they arrive from the provider.

        Providers with native streaming support should override this to yield
        real token chunks. The default implementation calls ``_call`` and yields
        the complete text as a single chunk (graceful degradation).
        """
        text, _, _ = self._call(prompt, **kwargs)
        yield text

    def generate(self, prompt: str, **kwargs) -> GenerationResult:
        start = time.monotonic()
        try:
            text, in_tok, out_tok = self._call(prompt, **kwargs)
        except Exception as e:  # noqa: BLE001 - normalize all provider failures
            raise ProviderError(f"{self.name}/{self.model_id}: {e}") from e
        latency = time.monotonic() - start
        cost = (in_tok / 1000) * self.pricing.get("input_per_1k", 0) + (
            out_tok / 1000
        ) * self.pricing.get("output_per_1k", 0)
        return GenerationResult(
            text=text,
            provider=self.name,
            model=self.model_id,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=round(cost, 6),
            latency_s=round(latency, 3),
        )

    def stream(self, prompt: str, **kwargs) -> Iterator[str]:
        """Public streaming interface — yields text chunks in real time.

        Uses native provider streaming when ``_stream`` is overridden; falls back
        to single-chunk yield if the provider does not support streaming.
        """
        yield from self._stream(prompt, **kwargs)
