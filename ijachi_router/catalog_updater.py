"""Automatic LLM Catalog & Pricing Auto-Updater for ijachi-llm-router.

Fetches dynamic pricing and model lists from remote registries and caches them to ~/.ijachi-llmr/models_cache.yaml.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
import yaml

_CACHE_DIR = Path.home() / ".ijachi-llmr"
_MODELS_CACHE_FILE = _CACHE_DIR / "models_cache.yaml"
_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


def fetch_remote_catalog() -> list[dict]:
    """Fetch current LLM models and token pricing rates from remote registry."""
    req = urllib.request.Request(
        _OPENROUTER_MODELS_URL,
        headers={"User-Agent": "ijachi-llm-router/0.1.0"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    raw_models = data.get("data", [])
    formatted_models = []

    for m in raw_models:
        model_id = m.get("id", "")
        pricing = m.get("pricing", {})
        prompt_cost = float(pricing.get("prompt", 0.0)) * 1000
        completion_cost = float(pricing.get("completion", 0.0)) * 1000
        context_len = int(m.get("context_length", 4096))

        tags = ["simple-qa"]
        if "code" in model_id.lower() or "coder" in model_id.lower():
            tags.append("code")
        if "r1" in model_id.lower() or "o1" in model_id.lower() or "reasoning" in model_id.lower():
            tags.append("reasoning")
        if "math" in model_id.lower():
            tags.append("math")

        provider = "openrouter"
        if "/" in model_id:
            provider = model_id.split("/")[0]

        formatted_models.append({
            "provider": provider,
            "model_id": model_id,
            "tags": tags,
            "input_per_1k": round(prompt_cost, 6),
            "output_per_1k": round(completion_cost, 6),
            "max_context": context_len,
            "speed_tier": "fast" if context_len <= 32768 else "medium",
        })

    return formatted_models


def update_catalog(force: bool = False) -> tuple[bool, str]:
    """Fetch latest remote catalog and save to ~/.ijachi-llmr/models_cache.yaml."""
    try:
        models = fetch_remote_catalog()
        if not models:
            return False, "No models received from remote registry."

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_data = {"models": models}
        _MODELS_CACHE_FILE.write_text(yaml.safe_dump(cache_data, sort_keys=False))

        return True, f"Successfully updated dynamic catalog with {len(models)} models."
    except Exception as e:
        return False, f"Failed to update remote catalog: {e}"


def get_cached_catalog_path() -> Path | None:
    """Return path to dynamic cached catalog if it exists."""
    if _MODELS_CACHE_FILE.exists():
        return _MODELS_CACHE_FILE
    return None
