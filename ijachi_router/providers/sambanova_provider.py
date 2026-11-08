"""sambanova adapter (OpenAI-compatible endpoint)."""

from ijachi_router.providers.openai_compat import OpenAICompatibleProvider


class SambaNovaProvider(OpenAICompatibleProvider):
    name = "sambanova"
    key_envs = ('SAMBANOVA_API_KEY',)
    key_error = 'SAMBANOVA_API_KEY environment variable not set.'
    base_url = 'https://api.sambanova.ai/v1'
    label = 'SambaNova API'
