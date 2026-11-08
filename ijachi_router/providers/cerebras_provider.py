"""cerebras adapter (OpenAI-compatible endpoint)."""

from ijachi_router.providers.openai_compat import OpenAICompatibleProvider


class CerebrasProvider(OpenAICompatibleProvider):
    name = "cerebras"
    key_envs = ('CEREBRAS_API_KEY',)
    key_error = 'CEREBRAS_API_KEY environment variable not set.'
    base_url = 'https://api.cerebras.ai/v1'
    label = 'Cerebras API'
