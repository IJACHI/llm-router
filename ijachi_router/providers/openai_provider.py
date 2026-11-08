"""openai adapter (OpenAI-compatible endpoint)."""

from ijachi_router.providers.openai_compat import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    key_envs = ('OPENAI_API_KEY',)
    key_error = 'OPENAI_API_KEY not set'
    base_url = None
    reasoning_quirks = True
    cache_read_multiplier = 0.5  # cached input bills at half price
