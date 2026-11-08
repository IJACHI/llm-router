"""deepseek adapter (OpenAI-compatible endpoint)."""

from ijachi_router.providers.openai_compat import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    name = "deepseek"
    key_envs = ('DEEPSEEK_API_KEY',)
    key_error = 'DEEPSEEK_API_KEY not set'
    base_url = 'https://api.deepseek.com'
