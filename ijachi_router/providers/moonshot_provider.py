"""moonshot adapter (OpenAI-compatible endpoint)."""

import os

from ijachi_router.providers.openai_compat import OpenAICompatibleProvider


class MoonshotProvider(OpenAICompatibleProvider):
    name = "moonshot"
    key_envs = ('MOONSHOT_API_KEY',)
    key_error = 'MOONSHOT_API_KEY not set'

    @property
    def base_url(self) -> str:  # type: ignore[override]
        # International keys (platform.moonshot.ai) use api.moonshot.ai; mainland-China keys
        # (platform.moonshot.cn) need MOONSHOT_BASE_URL=https://api.moonshot.cn/v1.
        return os.environ.get("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")
