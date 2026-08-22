"""Abstract provider interface. Every backend (OpenAI, Anthropic, local, ...)
implements this so the router core never has to know provider details."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator


def _messages_with_system_prompt(prompt: str, **kwargs) -> list[dict[str, str]]:
    """Return an OpenAI-compatible messages list with optional system prompt."""
    system_prompt = kwargs.get("system_prompt")
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return messages


def _stream_openai_compatible(
    api_key: str,
    model_id: str,
    prompt: str,
    base_url: str | None = None,
    **kwargs,
) -> Iterator[str]:
    """Shared streaming implementation for OpenAI-compatible providers."""
    try:
        import openai
    except ImportError as e:
        raise ProviderError(
            "openai package is required for streaming. Run: pip install openai"
        ) from e

    client_kwargs: dict = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = openai.OpenAI(**client_kwargs)

    system_prompt = kwargs.get("system_prompt")
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        for chunk in client.chat.completions.create(
            model=model_id,
            messages=messages,
            max_tokens=kwargs.get("max_tokens", 8192),
            stream=True,
        ):
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except Exception as err:
        raise ProviderError(f"Streaming call failed: {err}") from err


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

    def _ping(self) -> None:
        """Verify provider connectivity. Override in subclasses.

        Should raise ProviderError on failure.
        """
        raise ProviderError(f"{self.name} does not implement connectivity verification")

    def _stream(self, prompt: str, **kwargs) -> Iterator[str]:
        """Yield response text chunks in real time. Override in subclasses."""
        raise ProviderError(f"{self.name} does not implement streaming")

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
