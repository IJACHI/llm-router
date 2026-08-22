import os

from ijachi_router.providers.base import Provider, ProviderError, _stream_openai_compatible


class OpenAIProvider(Provider):
    name = "openai"

    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        try:
            import openai
        except ImportError as e:
            raise ProviderError(
                "openai package not installed. Run: pip install openai"
            ) from e

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ProviderError("OPENAI_API_KEY not set")

        try:
            client = openai.OpenAI(api_key=api_key)
            system_prompt = kwargs.get("system_prompt")
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            resp = client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                max_tokens=kwargs.get("max_tokens", 8192),
            )
            text = resp.choices[0].message.content or ""
            return text, resp.usage.prompt_tokens, resp.usage.completion_tokens
        except Exception as err:
            raise ProviderError(f"OpenAI API call failed for model '{self.model_id}': {err}") from err

    def _ping(self) -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ProviderError("OPENAI_API_KEY not set")
        try:
            import openai
            client = openai.OpenAI(api_key=api_key)
            client.models.list()
        except Exception as err:
            raise ProviderError(f"OpenAI connectivity check failed: {err}") from err

    def _stream(self, prompt: str, **kwargs):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ProviderError("OPENAI_API_KEY not set")
        yield from _stream_openai_compatible(api_key, self.model_id, prompt, **kwargs)
