"""Cerebras Cloud provider implementation for ultra-fast LPU inference."""

from __future__ import annotations

import os
from ijachi_router.providers.base import Provider, ProviderError, _stream_openai_compatible


class CerebrasProvider(Provider):
    """Cerebras Cloud provider wrapper via OpenAI-compatible SDK."""

    name = "cerebras"

    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        api_key = os.environ.get("CEREBRAS_API_KEY")
        if not api_key:
            raise ProviderError("CEREBRAS_API_KEY environment variable not set.")

        try:
            import openai
        except ImportError as e:
            raise ProviderError(
                "openai package is required for Cerebras Cloud integration. Install with: pip install openai"
            ) from e

        try:
            client = openai.OpenAI(api_key=api_key, base_url="https://api.cerebras.ai/v1")
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
            raise ProviderError(f"Cerebras API call failed for model '{self.model_id}': {err}") from err

    def _ping(self) -> None:
        api_key = os.environ.get("CEREBRAS_API_KEY")
        if not api_key:
            raise ProviderError("CEREBRAS_API_KEY not set")
        try:
            import openai
            client = openai.OpenAI(api_key=api_key, base_url="https://api.cerebras.ai/v1")
            client.models.list()
        except Exception as err:
            raise ProviderError(f"Cerebras connectivity check failed: {err}") from err

    def _stream(self, prompt: str, **kwargs):
        api_key = os.environ.get("CEREBRAS_API_KEY")
        if not api_key:
            raise ProviderError("CEREBRAS_API_KEY not set")
        yield from _stream_openai_compatible(
            api_key, self.model_id, prompt, base_url="https://api.cerebras.ai/v1", **kwargs
        )
