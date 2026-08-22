"""Secure LLM API Key Manager for ijachi-llm-router.

Manages provider API keys securely in ~/.ijachi-llmr/keys.env, loads keys automatically,
masks secrets in output, and tests live provider API connectivity.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ijachi_router.providers import REGISTRY
from ijachi_router.providers.base import ProviderError

_KEYS_FILE = Path.home() / ".ijachi-llmr" / "keys.env"

_PROVIDER_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "google": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "together": "TOGETHER_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "cohere": "COHERE_API_KEY",
    "huggingface": "HF_TOKEN",
    "fireworks": "FIREWORKS_API_KEY",
    "sambanova": "SAMBANOVA_API_KEY",
    "bedrock": "AWS_ACCESS_KEY_ID",
    "azure": "AZURE_OPENAI_API_KEY",
    "custom": "LOCAL_SERVER_URL",
    # NOTE: "local" (Ollama) is intentionally excluded — it needs no API key.
    # OLLAMA_HOST is a server binding setting, not an authentication secret.
}

# Env vars that must never be overwritten by the key manager
_PROTECTED_ENV_VARS = {"OLLAMA_HOST"}


def mask_secret(secret: str) -> str:
    """Mask sensitive key strings for terminal display (e.g. sk-ant-***1234)."""
    if not secret or len(secret) < 8:
        return "*****"
    return f"{secret[:6]}***{secret[-4:]}"


class KeyManager:
    """Manages provider API keys safely and loads them into environment variables."""

    def __init__(self, keys_file: Path | str | None = None):
        self.keys_file = Path(keys_file or _KEYS_FILE)

    def load_keys_into_env(self) -> None:
        """Load key values from keys.env file into os.environ if not already set."""
        if not self.keys_file.exists():
            return
        try:
            for line in self.keys_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key, val = key.strip(), val.strip().strip('"').strip("'")
                # Never overwrite protected system env vars (e.g. OLLAMA_HOST)
                if key in _PROTECTED_ENV_VARS:
                    continue
                if key and val and key not in os.environ:
                    os.environ[key] = val
        except Exception:
            pass

    def set_key(self, provider: str, key_value: str) -> str:
        """Set and save an API key for a provider."""
        provider_clean = provider.lower().strip()

        # Local Ollama needs no API key — OLLAMA_HOST is a server setting, not a secret
        if provider_clean == "local":
            return "Local Ollama provider needs no API key. Set OLLAMA_HOST in your shell to point to a custom Ollama server."

        env_var = _PROVIDER_ENV_VARS.get(provider_clean, f"{provider_clean.upper()}_API_KEY")

        # Safety: never write protected env vars to keys file
        if env_var in _PROTECTED_ENV_VARS:
            return f"'{env_var}' is a protected system variable and cannot be stored as a provider key."

        # Load existing keys
        existing: dict[str, str] = {}
        if self.keys_file.exists():
            for line in self.keys_file.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.strip()

        existing[env_var] = f'"{key_value.strip()}"'
        os.environ[env_var] = key_value.strip()

        self.keys_file.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"{k}={v}" for k, v in existing.items()]
        self.keys_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        return f"Successfully saved API key for provider '{provider_clean}' ({env_var})."

    def get_key(self, provider: str) -> str | None:
        """Retrieve API key for provider."""
        self.load_keys_into_env()
        env_var = _PROVIDER_ENV_VARS.get(provider.lower().strip(), f"{provider.upper()}_API_KEY")
        return os.getenv(env_var)

    def list_keys(self) -> dict[str, str]:
        """List all configured provider keys with masked values."""
        self.load_keys_into_env()
        result = {}
        for provider, env_var in _PROVIDER_ENV_VARS.items():
            val = os.getenv(env_var)
            if val:
                result[provider] = mask_secret(val)
        return result

    def clear_key(self, provider: str) -> str:
        """Remove API key for a provider."""
        provider_clean = provider.lower().strip()
        env_var = _PROVIDER_ENV_VARS.get(provider_clean, f"{provider_clean.upper()}_API_KEY")

        if env_var in os.environ:
            del os.environ[env_var]

        if not self.keys_file.exists():
            return f"No keys file found."

        lines = []
        for line in self.keys_file.read_text(encoding="utf-8").splitlines():
            if not line.startswith(f"{env_var}="):
                lines.append(line)

        self.keys_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return f"Successfully cleared API key for provider '{provider_clean}'."

    def test_keys(self) -> dict[str, bool]:
        """Check live API connectivity for all configured provider keys."""
        self.load_keys_into_env()
        status: dict[str, bool] = {}

        def _ping_provider(provider: str) -> bool:
            if provider not in REGISTRY:
                return False
            try:
                cls = REGISTRY[provider]
                instance = cls(
                    model_id="__ping__",
                    pricing={"input_per_1k": 0.0, "output_per_1k": 0.0},
                )
                instance._ping()
                return True
            except ProviderError:
                return False
            except Exception:
                return False

        for provider, env_var in _PROVIDER_ENV_VARS.items():
            if os.getenv(env_var):
                status[provider] = _ping_provider(provider)

        # Ollama is keyless; test reachability separately
        if "local" in REGISTRY:
            status["local"] = _ping_provider("local")

        return status
