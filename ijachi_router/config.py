"""Configuration loader for ijachi-llm-router.

Responsibilities
----------------
1. Load ``models.yaml`` from the repo root (or a custom path).
2. Load user preferences from ``~/.ijachi-llmr/config.yaml`` if present.
3. Detect which providers have API keys set in the environment.
4. Expose the merged config via ``RouterConfig``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_MODELS_YAML = _REPO_ROOT / "models.yaml"
_USER_CONFIG_PATH = Path.home() / ".ijachi-llmr" / "config.yaml"

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ModelConfig:
    """Represents one model entry from models.yaml."""
    provider: str
    model_id: str
    tags: list[str]
    input_per_1k: float
    output_per_1k: float
    max_context: int
    speed_tier: str  # fast | medium | slow

    @classmethod
    def from_dict(cls, d: dict) -> "ModelConfig":
        return cls(
            provider=d["provider"],
            model_id=d["model_id"],
            tags=d.get("tags", []),
            input_per_1k=float(d.get("input_per_1k", 0)),
            output_per_1k=float(d.get("output_per_1k", 0)),
            max_context=int(d.get("max_context", 4096)),
            speed_tier=d.get("speed_tier", "medium"),
        )

    @property
    def pricing(self) -> dict:
        return {
            "input_per_1k": self.input_per_1k,
            "output_per_1k": self.output_per_1k,
        }


@dataclass
class RouterConfig:
    """Merged runtime configuration."""
    models: list[ModelConfig] = field(default_factory=list)
    priority: str = "balanced"          # cost | speed | quality | balanced
    max_cost_per_call: float | None = None
    available_providers: set[str] = field(default_factory=set)

    # ── Derived helpers ─────────────────────────────────────────────────────

    def models_for_provider(self, provider: str) -> list[ModelConfig]:
        return [m for m in self.models if m.provider == provider]

    def available_models(self) -> list[ModelConfig]:
        """Return only models whose provider has a key configured."""
        return [m for m in self.models if m.provider in self.available_providers]

    def models_for_category(self, category: str) -> list[ModelConfig]:
        """Return available models that have *category* in their tags."""
        return [m for m in self.available_models() if category in m.tags]


# ---------------------------------------------------------------------------
# Provider availability detection
# ---------------------------------------------------------------------------

_PROVIDER_ENV_KEYS: dict[str, str | None] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "local": None,  # Ollama needs no API key
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "together": "TOGETHER_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "cohere": "COHERE_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "sambanova": "SAMBANOVA_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "huggingface": "HF_TOKEN",
    "custom": None,  # Local custom server (e.g. vLLM/LM Studio)
    "azure": "AZURE_OPENAI_API_KEY",
    "bedrock": "AWS_ACCESS_KEY_ID",
}




def _detect_available_providers(models: list[ModelConfig]) -> set[str]:
    """Return provider names that are usable based on env + model list."""
    listed_providers = {m.provider for m in models}
    available: set[str] = set()
    for provider in listed_providers:
        env_key = _PROVIDER_ENV_KEYS.get(provider)
        if env_key is None:
            # No key needed (local/Ollama)
            available.add(provider)
        elif os.environ.get(env_key):
            available.add(provider)
    return available


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _load_models(path: Path | str) -> list[ModelConfig]:
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [ModelConfig.from_dict(m) for m in data.get("models", [])]


def _load_user_config() -> dict[str, Any]:
    if not _USER_CONFIG_PATH.exists():
        return {}
    with _USER_CONFIG_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_config(models_yaml: str | Path | None = None) -> RouterConfig:
    """Load and return the merged RouterConfig.

    Args:
        models_yaml: Override path to models.yaml. Defaults to dynamic cache
                     or the bundled catalog in models.yaml.

    Returns:
        A fully populated RouterConfig.
    """
    if models_yaml:
        yaml_path = Path(models_yaml)
    else:
        try:
            from ijachi_router.catalog_updater import get_cached_catalog_path
            cached = get_cached_catalog_path()
            yaml_path = cached if cached else _DEFAULT_MODELS_YAML
        except Exception:
            yaml_path = _DEFAULT_MODELS_YAML

    models = _load_models(yaml_path)

    user = _load_user_config()
    priority = user.get("priority", "balanced")
    if priority not in {"cost", "speed", "quality", "balanced"}:
        priority = "balanced"

    max_cost = user.get("max_cost_per_call")
    if max_cost is not None:
        max_cost = float(max_cost)

    available = _detect_available_providers(models)

    return RouterConfig(
        models=models,
        priority=priority,
        max_cost_per_call=max_cost,
        available_providers=available,
    )

