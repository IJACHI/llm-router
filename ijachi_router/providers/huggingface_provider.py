"""huggingface adapter (OpenAI-compatible endpoint)."""

from ijachi_router.providers.openai_compat import OpenAICompatibleProvider


class HuggingFaceProvider(OpenAICompatibleProvider):
    name = "huggingface"
    key_envs = ('HF_TOKEN', 'HUGGINGFACE_API_KEY')
    key_error = 'HF_TOKEN or HUGGINGFACE_API_KEY environment variable not set.'
    base_url = 'https://router.huggingface.co/v1'
    label = 'Hugging Face API'
