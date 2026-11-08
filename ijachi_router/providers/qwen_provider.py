"""qwen adapter (OpenAI-compatible endpoint)."""

from ijachi_router.providers.openai_compat import OpenAICompatibleProvider


class QwenProvider(OpenAICompatibleProvider):
    name = "qwen"
    key_envs = ('DASHSCOPE_API_KEY', 'QWEN_API_KEY')
    key_error = 'DASHSCOPE_API_KEY or QWEN_API_KEY not set'
    base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
