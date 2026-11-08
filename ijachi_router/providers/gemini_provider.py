"""gemini adapter (OpenAI-compatible endpoint)."""

from ijachi_router.providers.openai_compat import OpenAICompatibleProvider


class GeminiProvider(OpenAICompatibleProvider):
    name = "gemini"
    key_envs = ('GEMINI_API_KEY', 'GOOGLE_API_KEY')
    key_error = 'GEMINI_API_KEY or GOOGLE_API_KEY not set'
    base_url = 'https://generativelanguage.googleapis.com/v1beta/openai/'
