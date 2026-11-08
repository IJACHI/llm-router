"""openrouter adapter (OpenAI-compatible endpoint)."""

from ijachi_router.providers.openai_compat import OpenAICompatibleProvider


class OpenRouterProvider(OpenAICompatibleProvider):
    name = "openrouter"
    key_envs = ('OPENROUTER_API_KEY',)
    key_error = 'OPENROUTER_API_KEY not set'
    base_url = 'https://openrouter.ai/api/v1'
