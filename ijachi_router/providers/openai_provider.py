import os
from typing import Iterator

from ijachi_router.providers.base import Provider, ProviderError


class OpenAIProvider(Provider):
    name = "openai"

    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        try:
            import openai  # noqa: F401
        except ImportError as e:
            raise ProviderError(
                "openai package not installed. Run: pip install openai"
            ) from e

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ProviderError("OPENAI_API_KEY not set")

        try:
            from ijachi_router.providers.client_pool import get_cached_openai_client
            client = get_cached_openai_client(api_key=api_key)
            resp = client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=kwargs.get("max_tokens", 1024),
            )
            text = resp.choices[0].message.content or ""
            return text, resp.usage.prompt_tokens, resp.usage.completion_tokens
        except Exception as err:
            raise ProviderError(f"OpenAI API call failed for model '{self.model_id}': {err}") from err

    def _stream(self, prompt: str, **kwargs) -> Iterator[str]:
        """Yield token chunks in real time from the OpenAI streaming API."""
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ProviderError("OPENAI_API_KEY not set")

        try:
            from ijachi_router.providers.client_pool import get_cached_openai_client
            client = get_cached_openai_client(api_key=api_key)
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
            raise ProviderError(f"OpenAI streaming failed for model '{self.model_id}': {err}") from err
