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
        system_prompt = kwargs.get("system_prompt")
        params = {
            "model": self.model_id,
            "max_tokens": kwargs.get("max_tokens", 8192),
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            params["system"] = system_prompt

        resp = client.messages.create(**params)
        text = "".join(block.text for block in resp.content if hasattr(block, "text"))
        return text, resp.usage.input_tokens, resp.usage.output_tokens

    def _ping(self) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ProviderError("ANTHROPIC_API_KEY not set")
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            client.models.list()
        except Exception as err:
            raise ProviderError(f"Anthropic connectivity check failed: {err}") from err

    def _stream(self, prompt: str, **kwargs):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ProviderError("ANTHROPIC_API_KEY not set")
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            system_prompt = kwargs.get("system_prompt")
            with client.messages.stream(
                model=self.model_id,
                max_tokens=kwargs.get("max_tokens", 8192),
                messages=[{"role": "user", "content": prompt}],
                system=system_prompt or anthropic.NOT_GIVEN,
            ) as stream:
                for text in stream.text_stream:
                    if text:
                        yield text
        except Exception as err:
            raise ProviderError(f"Anthropic streaming failed: {err}") from err
