"""Custom OpenAI-compatible provider for vLLM, LM Studio, or local self-hosted endpoints."""

from __future__ import annotations

import os
from ijachi_router.providers.base import Provider, ProviderError, _stream_openai_compatible


class CustomProvider(Provider):
    """Custom OpenAI-compatible local or remote inference server provider wrapper."""

    name = "custom"

    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        base_url = (
            os.environ.get("LOCAL_SERVER_URL")
            or os.environ.get("CUSTOM_LLM_BASE_URL")
            or "http://localhost:1234/v1"
        )
        api_key = os.environ.get("CUSTOM_LLM_API_KEY", "not-needed")

        try:
            import openai
        except ImportError as e:
            raise ProviderError(
                "openai package is required for Custom/vLLM endpoints. Install with: pip install openai"
            ) from e

        try:
            client = openai.OpenAI(api_key=api_key, base_url=base_url)
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
            raise ProviderError(f"Custom LLM server call failed at base URL '{base_url}': {err}") from err

    def _ping(self) -> None:
        base_url = (
            os.environ.get("LOCAL_SERVER_URL")
            or os.environ.get("CUSTOM_LLM_BASE_URL")
            or "http://localhost:1234/v1"
        )
        api_key = os.environ.get("CUSTOM_LLM_API_KEY", "not-needed")
        try:
            import openai
            client = openai.OpenAI(api_key=api_key, base_url=base_url)
            client.models.list()
        except Exception as err:
            raise ProviderError(f"Custom LLM server connectivity check failed at '{base_url}': {err}") from err

    def _stream(self, prompt: str, **kwargs):
        base_url = (
            os.environ.get("LOCAL_SERVER_URL")
            or os.environ.get("CUSTOM_LLM_BASE_URL")
            or "http://localhost:1234/v1"
        )
        api_key = os.environ.get("CUSTOM_LLM_API_KEY", "not-needed")
        yield from _stream_openai_compatible(
            api_key, self.model_id, prompt, base_url=base_url, **kwargs
        )
