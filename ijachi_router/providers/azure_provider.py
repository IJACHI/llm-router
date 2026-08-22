"""Azure OpenAI provider implementation for enterprise deployments."""

from __future__ import annotations

import os
from ijachi_router.providers.base import Provider, ProviderError


class AzureOpenAIProvider(Provider):
    """Azure OpenAI service provider wrapper."""

    name = "azure"

    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        if not api_key or not endpoint:
            raise ProviderError(
                "AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT environment variables must be set."
            )

        try:
            import openai
        except ImportError as e:
            raise ProviderError(
                "openai package is required for Azure OpenAI integration. Install with: pip install openai"
            ) from e

        try:
            client = openai.AzureOpenAI(
                api_key=api_key,
                azure_endpoint=endpoint,
                api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01"),
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
            raise ProviderError(f"Azure OpenAI call failed for deployment '{self.model_id}': {err}") from err

    def _ping(self) -> None:
        api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        if not api_key or not endpoint:
            raise ProviderError("AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT must be set")
        try:
            import openai
            client = openai.AzureOpenAI(
                api_key=api_key,
                azure_endpoint=endpoint,
                api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01"),
            )
            client.models.list()
        except Exception as err:
            raise ProviderError(f"Azure OpenAI connectivity check failed: {err}") from err

    def _stream(self, prompt: str, **kwargs):
        api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        if not api_key or not endpoint:
            raise ProviderError("AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT must be set")
        try:
            import openai
            client = openai.AzureOpenAI(
                api_key=api_key,
                azure_endpoint=endpoint,
                api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01"),
            )
            system_prompt = kwargs.get("system_prompt")
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            for chunk in client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                max_tokens=kwargs.get("max_tokens", 1024),
                stream=True,
            ):
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as err:
            raise ProviderError(f"Azure OpenAI streaming failed: {err}") from err
