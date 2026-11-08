"""groq adapter (OpenAI-compatible endpoint)."""

from ijachi_router.providers.openai_compat import OpenAICompatibleProvider


class GroqProvider(OpenAICompatibleProvider):
    name = "groq"
    key_envs = ('GROQ_API_KEY',)
    key_error = 'GROQ_API_KEY not set'
    base_url = 'https://api.groq.com/openai/v1'
