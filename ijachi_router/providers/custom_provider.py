"""Custom OpenAI-compatible provider for vLLM, LM Studio, or self-hosted endpoints."""

import os

from ijachi_router.providers.openai_compat import OpenAICompatibleProvider


class CustomProvider(OpenAICompatibleProvider):
    name = "custom"
    label = "Custom LLM server"

    def _base(self) -> str:
        return (
            os.environ.get("LOCAL_SERVER_URL")
            or os.environ.get("CUSTOM_LLM_BASE_URL")
            or "http://localhost:1234/v1"
        )

    def _client(self, kwargs: dict):
        openai = self._openai()
        self.label = f"Custom LLM server at base URL '{self._base()}'"
        return openai.OpenAI(
            api_key=os.environ.get("CUSTOM_LLM_API_KEY", "not-needed"),
            base_url=self._base(),
            timeout=self._timeout(kwargs),
        )
