import os

from ijachi_router.providers.base import Provider, ProviderError


class AnthropicProvider(Provider):
    name = "anthropic"

    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        try:
            import anthropic
        except ImportError as e:
            raise ProviderError(
                "anthropic package not installed. Run: pip install anthropic"
            ) from e

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ProviderError("ANTHROPIC_API_KEY not set")

        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=self.model_id,
            max_tokens=kwargs.get("max_tokens", 1024),
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in resp.content if hasattr(block, "text"))
        return text, resp.usage.input_tokens, resp.usage.output_tokens
