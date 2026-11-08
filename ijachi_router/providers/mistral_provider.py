"""mistral adapter (OpenAI-compatible endpoint)."""

from ijachi_router.providers.openai_compat import OpenAICompatibleProvider


class MistralProvider(OpenAICompatibleProvider):
    name = "mistral"
    key_envs = ('MISTRAL_API_KEY',)
    key_error = 'MISTRAL_API_KEY not set'
    base_url = 'https://api.mistral.ai/v1'
