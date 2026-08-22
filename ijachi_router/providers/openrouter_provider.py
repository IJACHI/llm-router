import os
from typing import Iterator

from ijachi_router.providers.base import Provider, ProviderError


class OpenRouterProvider(Provider):
    name = "openrouter"

    _BASE_URL = "https://openrouter.ai/api/v1"

    def _get_client(self, api_key: str):
        try:
            import openai
        except ImportError as e:
            raise ProviderError(
                "openai package not installed (required for OpenRouter API calls). Run: pip install openai"
            ) from e
        return openai.OpenAI(api_key=api_key, base_url=self._BASE_URL)

    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ProviderError("OPENROUTER_API_KEY not set")

        try:
            client = self._get_client(api_key)
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
            raise ProviderError(f"OpenRouter API call failed for model '{self.model_id}': {err}") from err

    def _stream(self, prompt: str, **kwargs) -> Iterator[str]:
        """Yield token chunks in real time from OpenRouter's streaming API (OpenAI-compatible)."""
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ProviderError("OPENROUTER_API_KEY not set")

        try:
            client = self._get_client(api_key)
            with client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=kwargs.get("max_tokens", 1024),
                stream=True,
            ) as stream:
                for chunk in stream:
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        yield delta
        except Exception as err:
            raise ProviderError(f"OpenRouter streaming failed for model '{self.model_id}': {err}") from err
