import os
from ijachi_router.providers.base import Provider, ProviderError, _stream_openai_compatible


class QwenProvider(Provider):
    name = "qwen"

    def _call(self, prompt: str, **kwargs) -> tuple[str, int, int]:
        api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY")
        if not api_key:
            raise ProviderError("DASHSCOPE_API_KEY or QWEN_API_KEY not set")

        try:
            import openai
        except ImportError as e:
            raise ProviderError(
                "openai package not installed (required for Qwen API calls). Run: pip install openai"
            ) from e

        client = openai.OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        resp = client.chat.completions.create(
            model=self.model_id,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=kwargs.get("max_tokens", 1024),
        )
        text = resp.choices[0].message.content or ""
        in_tokens = resp.usage.prompt_tokens if resp.usage else 0
        out_tokens = resp.usage.completion_tokens if resp.usage else 0
        return text, in_tokens, out_tokens

    def _ping(self) -> None:
        api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY")
        if not api_key:
            raise ProviderError("DASHSCOPE_API_KEY or QWEN_API_KEY not set")
        try:
            import openai
            client = openai.OpenAI(api_key=api_key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
            client.models.list()
        except Exception as err:
            raise ProviderError(f"Qwen connectivity check failed: {err}") from err

    def _stream(self, prompt: str, **kwargs):
        api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY")
        if not api_key:
            raise ProviderError("DASHSCOPE_API_KEY or QWEN_API_KEY not set")
        yield from _stream_openai_compatible(
            api_key,
            self.model_id,
            prompt,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            **kwargs,
        )
