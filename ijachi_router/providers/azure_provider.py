"""Azure OpenAI provider (deployment name is the model_id)."""

import os

from ijachi_router.providers.base import ProviderError
from ijachi_router.providers.openai_compat import OpenAICompatibleProvider


class AzureOpenAIProvider(OpenAICompatibleProvider):
    name = "azure"
    label = "Azure OpenAI"
    reasoning_quirks = True
    cache_read_multiplier = 0.5  # cached input bills at half price

    def _client(self, kwargs: dict):
        api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        if not api_key or not endpoint:
            raise ProviderError("AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT environment variables must be set.")
        openai = self._openai()
        return openai.AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01"),
            timeout=self._timeout(kwargs),
        )
