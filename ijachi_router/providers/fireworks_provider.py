"""fireworks adapter (OpenAI-compatible endpoint)."""

from ijachi_router.providers.openai_compat import OpenAICompatibleProvider


class FireworksProvider(OpenAICompatibleProvider):
    name = "fireworks"
    key_envs = ('FIREWORKS_API_KEY',)
    key_error = 'FIREWORKS_API_KEY environment variable not set.'
    base_url = 'https://api.fireworks.ai/inference/v1'
    label = 'Fireworks AI API'
