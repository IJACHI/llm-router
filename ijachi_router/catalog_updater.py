"""Model price refresher for ijachi-llm-router.

The bundled ``models.yaml`` is the curated source of truth (model ids, providers, tags,
quality tiers). ``update_catalog()`` only refreshes *prices and context windows* for curated
entries that declare an ``openrouter_id``, using OpenRouter's public model list, and stores
them as an overlay in ``~/.ijachi-llmr/models_cache.yaml``. ``load_config`` applies that
overlay on top of the bundled catalog, so a refresh can never introduce unusable model ids.
"""

from __future__ import annotations

import datetime
import json
import urllib.request
from pathlib import Path

import yaml

_CACHE_DIR = Path.home() / ".ijachi-llmr"
_MODELS_CACHE_FILE = _CACHE_DIR / "models_cache.yaml"
_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_OVERLAY_FORMAT = "price_overlay_v1"


def fetch_remote_catalog() -> list[dict]:
    """Fetch OpenRouter's public model list (ids are OpenRouter ids, prices per 1k tokens)."""
    req = urllib.request.Request(_OPENROUTER_MODELS_URL, headers={"User-Agent": "ijachi-llm-router"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    out = []
    for m in data.get("data", []):
        pricing = m.get("pricing", {})
        try:
            prompt_cost = float(pricing.get("prompt", 0.0)) * 1000
            completion_cost = float(pricing.get("completion", 0.0)) * 1000
        except (TypeError, ValueError):
            continue
        out.append({
            "model_id": m.get("id", ""),
            "input_per_1k": round(prompt_cost, 6),
            "output_per_1k": round(completion_cost, 6),
            "max_context": int(m.get("context_length") or 0),
        })
    return out


def _plausible(hit: dict) -> bool:
    """Reject placeholder prices (OpenRouter uses -1 for dynamic routers) and absurd values."""
    i, o = hit["input_per_1k"], hit["output_per_1k"]
    return 0 <= i <= 1.0 and 0 <= o <= 1.0 and (i > 0 or o > 0)


def _bundled_entries() -> list[dict]:
    from ijachi_router.config import _DEFAULT_MODELS_YAML
    return yaml.safe_load(_DEFAULT_MODELS_YAML.read_text(encoding="utf-8")).get("models", [])


def update_catalog(force: bool = False) -> tuple[bool, str]:
    """Refresh prices for curated models and save them as an overlay."""
    try:
        remote = fetch_remote_catalog()
        if not remote:
            return False, "No models received from remote registry."
        by_id = {m["model_id"]: m for m in remote}

        prices: dict[str, dict] = {}
        changes: list[str] = []
        for entry in _bundled_entries():
            rid = entry.get("openrouter_id")
            hit = by_id.get(rid) if rid else None
            if hit is None:
                # Fallback match: same model id under the provider's namespace.
                hit = by_id.get(entry["model_id"]) or by_id.get(f"{entry['provider']}/{entry['model_id']}")
            if hit is None or not _plausible(hit):
                continue
            key = f"{entry['provider']}/{entry['model_id']}"
            new = {"input_per_1k": hit["input_per_1k"], "output_per_1k": hit["output_per_1k"]}
            if hit.get("max_context"):
                new["max_context"] = hit["max_context"]
            prices[key] = new
            if (abs(new["input_per_1k"] - float(entry.get("input_per_1k", 0))) > 1e-9
                    or abs(new["output_per_1k"] - float(entry.get("output_per_1k", 0))) > 1e-9):
                changes.append(key)

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _MODELS_CACHE_FILE.write_text(yaml.safe_dump({
            "format": _OVERLAY_FORMAT,
            "source": _OPENROUTER_MODELS_URL,
            "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "prices": prices,
        }, sort_keys=False))
        detail = f" Changed vs bundled catalog: {', '.join(changes)}." if changes else ""
        return True, f"Successfully updated prices for {len(prices)} curated models.{detail}"
    except Exception as e:
        return False, f"Failed to update remote catalog: {e}"


def get_cached_catalog_path() -> Path | None:
    """Return path to the price overlay if it exists."""
    if _MODELS_CACHE_FILE.exists():
        return _MODELS_CACHE_FILE
    return None


def load_price_overlay() -> dict[str, dict]:
    """Prices keyed by 'provider/model_id'. Legacy full-catalog caches are ignored."""
    path = get_cached_catalog_path()
    if not path:
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    if data.get("format") != _OVERLAY_FORMAT:
        return {}
    return data.get("prices") or {}
