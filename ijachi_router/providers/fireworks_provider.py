"""Fireworks AI provider implementation for high-speed open model hosting."""

from __future__ import annotations

import os
from ijachi_router.providers.base import Provider, ProviderError


class FireworksProvider(Provider):
    """Fireworks AI provider wrapper via OpenAI-compatible SDK."""

    name = "fireworks"

    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        api_key = os.environ.get("FIREWORKS_API_KEY")
        if not api_key:
            raise ProviderError("FIREWORKS_API_KEY environment variable not set.")

        try:
            import openai
        except ImportError as e:
            raise ProviderError(
                "openai package is required for Fireworks AI integration. Install with: pip install openai"
            ) from e

        try:
            client = openai.OpenAI(api_key=api_key, base_url="https://api.fireworks.ai/inference/v1")
            resp = client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=kwargs.get("max_tokens", 1024),
            )
            text = resp.choices[0].message.content or ""
            in_tokens = resp.usage.prompt_tokens if resp.usage else 0
            out_tokens = resp.usage.completion_tokens if resp.usage else 0
            return text, in_tokens, out_tokens
        except Exception as err:
            raise ProviderError(f"Fireworks AI call failed for model '{self.model_id}': {err}") from err
