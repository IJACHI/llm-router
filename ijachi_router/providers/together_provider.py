"""together adapter (OpenAI-compatible endpoint)."""

from ijachi_router.providers.openai_compat import OpenAICompatibleProvider


class TogetherProvider(OpenAICompatibleProvider):
    name = "together"
    key_envs = ('TOGETHER_API_KEY',)
    key_error = 'TOGETHER_API_KEY not set'
    base_url = 'https://api.together.xyz/v1'
