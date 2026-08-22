import os
from typing import Iterator

from ijachi_router.providers.base import Provider, ProviderError


class AnthropicProvider(Provider):
    name = "anthropic"

    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        try:
            import anthropic  # noqa: F401
        except ImportError as e:
            raise ProviderError(
                "anthropic package not installed. Run: pip install anthropic"
            ) from e

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ProviderError("ANTHROPIC_API_KEY not set")

        from ijachi_router.providers.client_pool import get_cached_anthropic_client
        client = get_cached_anthropic_client(api_key=api_key)
        resp = client.messages.create(
            model=self.model_id,
            max_tokens=kwargs.get("max_tokens", 1024),
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in resp.content if hasattr(block, "text"))
        return text, resp.usage.input_tokens, resp.usage.output_tokens

    def _stream(self, prompt: str, **kwargs) -> Iterator[str]:
        """Yield token chunks in real time from the Anthropic streaming API."""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ProviderError("ANTHROPIC_API_KEY not set")

        try:
            from ijachi_router.providers.client_pool import get_cached_anthropic_client
            client = get_cached_anthropic_client(api_key=api_key)
            with client.messages.stream(
                model=self.model_id,
                max_tokens=kwargs.get("max_tokens", 1024),
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text_chunk in stream.text_stream:
                    if text_chunk:
                        yield text_chunk
        except Exception as err:
            raise ProviderError(f"Anthropic streaming failed for model '{self.model_id}': {err}") from err
