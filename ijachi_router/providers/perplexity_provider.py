"""perplexity adapter (OpenAI-compatible endpoint)."""

from ijachi_router.providers.openai_compat import OpenAICompatibleProvider


class PerplexityProvider(OpenAICompatibleProvider):
    name = "perplexity"
    key_envs = ('PERPLEXITY_API_KEY',)
    key_error = 'PERPLEXITY_API_KEY not set'
    base_url = 'https://api.perplexity.ai'
    native_tools = False
