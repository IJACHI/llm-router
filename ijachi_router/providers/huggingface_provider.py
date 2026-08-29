"""Hugging Face Inference API provider implementation."""

from __future__ import annotations

import os
from ijachi_router.providers.base import Provider, ProviderError


class HuggingFaceProvider(Provider):
    """Hugging Face Serverless Inference provider wrapper."""

    name = "huggingface"

    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        api_key = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_API_KEY")
        if not api_key:
            raise ProviderError("HF_TOKEN or HUGGINGFACE_API_KEY environment variable not set.")

        try:
            import openai
        except ImportError as e:
            raise ProviderError(
                "openai package is required for Hugging Face integration. Install with: pip install openai"
            ) from e

        try:
            client = openai.OpenAI(
                api_key=api_key,
                base_url="https://api-inference.huggingface.co/v1",
            )
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
            raise ProviderError(f"Hugging Face API call failed for model '{self.model_id}': {err}") from err
