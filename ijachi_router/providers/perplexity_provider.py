import os
from ijachi_router.providers.base import Provider, ProviderError


class PerplexityProvider(Provider):
    name = "perplexity"

    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        api_key = os.environ.get("PERPLEXITY_API_KEY")
        if not api_key:
            raise ProviderError("PERPLEXITY_API_KEY not set")

        try:
            import openai
        except ImportError as e:
            raise ProviderError(
                "openai package not installed (required for Perplexity API calls). Run: pip install openai"
            ) from e

        client = openai.OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
        resp = client.chat.completions.create(
            model=self.model_id,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=kwargs.get("max_tokens", 1024),
        )
        text = resp.choices[0].message.content or ""
        in_tokens = resp.usage.prompt_tokens if resp.usage else 0
        out_tokens = resp.usage.completion_tokens if resp.usage else 0
        return text, in_tokens, out_tokens
