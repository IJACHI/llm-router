import os
from ijachi_router.providers.base import Provider, ProviderError, _stream_openai_compatible


class GroqProvider(Provider):
    name = "groq"

    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ProviderError("GROQ_API_KEY not set")

        try:
            import openai
        except ImportError as e:
            raise ProviderError(
                "openai package not installed (required for Groq API calls). Run: pip install openai"
            ) from e

        try:
            client = openai.OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
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
            in_tokens = resp.usage.prompt_tokens if resp.usage else 0
            out_tokens = resp.usage.completion_tokens if resp.usage else 0
            return text, in_tokens, out_tokens
        except Exception as err:
            raise ProviderError(f"Groq API call failed for model '{self.model_id}': {err}") from err

    def _ping(self) -> None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ProviderError("GROQ_API_KEY not set")
        try:
            import openai
            client = openai.OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
            client.models.list()
        except Exception as err:
            raise ProviderError(f"Groq connectivity check failed: {err}") from err

    def _stream(self, prompt: str, **kwargs):
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ProviderError("GROQ_API_KEY not set")
        yield from _stream_openai_compatible(
            api_key, self.model_id, prompt, base_url="https://api.groq.com/openai/v1", **kwargs
        )
