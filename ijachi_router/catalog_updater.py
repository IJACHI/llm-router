"""Automatic LLM Catalog & Pricing Auto-Updater for ijachi-llm-router.

Fetches dynamic pricing and model lists from remote registries, merges pricing
updates into the curated provider matrix, and caches the result to
~/.ijachi-llmr/models_cache.yaml.

Only providers that are registered in ``ijachi_router.providers.REGISTRY``
are kept, so the curated 20-provider matrix is never poisoned by unfiltered
remote model dumps.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import asdict
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


def _model_config_to_dict(m) -> dict:
    """Serialize a ModelConfig-like object to a dict for YAML caching."""
    return {
        "model_id": m.model_id,
        "provider": m.provider,
        "tags": m.tags,
        "input_per_1k": m.input_per_1k,
        "output_per_1k": m.output_per_1k,
        "max_context": m.max_context,
        "speed_tier": m.speed_tier,
    }


def update_catalog(force: bool = False) -> tuple[bool, str]:
    """Fetch latest remote catalog and update pricing for curated providers only.

    The bundled ``models.yaml`` is used as the source of truth. Only known
    providers (those present in ``ijachi_router.providers.REGISTRY``) are
    considered, so the curated routing matrix cannot be poisoned by an
    unfiltered remote dump.
    """
    try:
        from ijachi_router.config import default_models_yaml_path, ModelConfig
        from ijachi_router.providers import REGISTRY

        bundled_path = default_models_yaml_path()
        bundled_models = []
        if bundled_path.exists():
            with bundled_path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            bundled_models = [ModelConfig.from_dict(m) for m in data.get("models", [])]

        bundled_lookup = {(m.provider, m.model_id): m for m in bundled_models}
        remote_models = fetch_remote_catalog()

        # Only keep remote entries whose provider is in our registry.
        known_remote = [m for m in remote_models if m["provider"] in REGISTRY]

        updated = 0
        added = 0
        for remote in known_remote:
            key = (remote["provider"], remote["model_id"])
            if key in bundled_lookup:
                existing = bundled_lookup[key]
                existing.input_per_1k = remote["input_per_1k"]
                existing.output_per_1k = remote["output_per_1k"]
                updated += 1
            else:
                # Add a curated new model from a known provider.
                bundled_lookup[key] = ModelConfig.from_dict(remote)
                added += 1

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_data = {
            "version": "1.0",
            "source": "remote-curated",
            "models": [_model_config_to_dict(m) for m in bundled_lookup.values()],
        }
        _MODELS_CACHE_FILE.write_text(yaml.safe_dump(cache_data, sort_keys=False), encoding="utf-8")

        return True, (
            f"Updated pricing for {updated} curated model(s); added {added} new "
            f"model(s) from {len(known_remote)} remote entries."
        )
    except Exception as e:
        return False, f"Failed to update remote catalog: {e}"


def restore_default_catalog() -> tuple[bool, str]:
    """Delete the dynamic catalog cache and fall back to bundled models.yaml."""
    try:
        if _MODELS_CACHE_FILE.exists():
            _MODELS_CACHE_FILE.unlink()
            return True, "Dynamic catalog cache removed; using bundled models.yaml."
        return True, "No dynamic catalog cache to remove; already using bundled models.yaml."
    except Exception as e:
        return False, f"Failed to remove catalog cache: {e}"


def get_cached_catalog_path() -> Path | None:
    """Return path to dynamic cached catalog if it exists."""
    if _MODELS_CACHE_FILE.exists():
        return _MODELS_CACHE_FILE
    return None
