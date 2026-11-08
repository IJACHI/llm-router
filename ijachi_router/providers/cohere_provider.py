"""cohere adapter (OpenAI-compatible endpoint)."""

from ijachi_router.providers.openai_compat import OpenAICompatibleProvider


class CohereProvider(OpenAICompatibleProvider):
    name = "cohere"
    key_envs = ('COHERE_API_KEY',)
    key_error = 'COHERE_API_KEY not set'
    base_url = 'https://api.cohere.ai/compatibility/v1'
