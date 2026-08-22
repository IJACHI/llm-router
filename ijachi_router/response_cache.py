"""High-performance in-memory and persistent response cache for ijachi-code.

Provides sub-millisecond (<1ms) response retrieval for repeated queries and prompt
fragments, eliminating redundant remote LLM inference and reducing costs to $0.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.table import Table

from ijachi_router.providers.base import GenerationResult

console = Console()


@dataclass
class CacheEntry:
    key_hash: str
    result_dict: dict[str, Any]
    created_at: float
    ttl_seconds: float
    hits: int = 0

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_seconds


class ResponseCache:
    """Fast in-memory LRU + on-disk persistent cache for GenerationResult objects."""

    _instance: ResponseCache | None = None

    def __new__(cls, *args, **kwargs) -> ResponseCache:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        max_entries: int = 2000,
        default_ttl: float = 86400.0,  # 24 hours
        enabled: bool = True,
    ):
        if getattr(self, "_initialized", False):
            return
        self.enabled = enabled
        self.max_entries = max_entries
        self.default_ttl = default_ttl
        self.cache_dir = Path(cache_dir or Path.home() / ".ijachi-llmr").resolve()
        self._cache_file = self.cache_dir / "response_cache.json"

        self._memory_cache: dict[str, CacheEntry] = {}
        self._hits = 0
        self._misses = 0
        self._saved_cost_usd = 0.0

        self._load_from_disk()
        self._initialized = True

    def _normalize_key(self, prompt: str, model_id: str | None = None, priority: str | None = None) -> str:
        """Create a deterministic SHA-256 hash from prompt text and optional model/priority."""
        norm_prompt = " ".join(prompt.strip().split())
        raw_key = f"{norm_prompt}|{model_id or 'auto'}|{priority or 'balanced'}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def _load_from_disk(self) -> None:
        """Load persisted cache records from disk."""
        if not self._cache_file.exists():
            return
        try:
            data = json.loads(self._cache_file.read_text(encoding="utf-8"))
            now = time.time()
            for key, val in data.items():
                entry = CacheEntry(
                    key_hash=val["key_hash"],
                    result_dict=val["result_dict"],
                    created_at=val["created_at"],
                    ttl_seconds=val["ttl_seconds"],
                    hits=val.get("hits", 0),
                )
                if not entry.is_expired:
                    self._memory_cache[key] = entry
        except Exception:
            pass

    def _save_to_disk(self) -> None:
        """Flush active memory cache records to disk."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            data = {
                k: asdict(v) for k, v in self._memory_cache.items() if not v.is_expired
            }
            self._cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def get(
        self,
        prompt: str,
        model_id: str | None = None,
        priority: str | None = None,
    ) -> GenerationResult | None:
        """Retrieve a cached GenerationResult if present and not expired."""
        if not self.enabled:
            return None

        key = self._normalize_key(prompt, model_id, priority)
        entry = self._memory_cache.get(key)
        if entry is None:
            self._misses += 1
            return None

        if entry.is_expired:
            del self._memory_cache[key]
            self._misses += 1
            return None

        entry.hits += 1
        self._hits += 1
        d = entry.result_dict

        res = GenerationResult(
            text=d["text"],
            provider=f"{d['provider']} (cache)",
            model=d["model"],
            input_tokens=0,
            output_tokens=d.get("output_tokens", 0),
            cost_usd=0.0,
            latency_s=0.001,
            category=d.get("category", "general"),
            complexity=d.get("complexity", 0.5),
            cost_saved_usd=d.get("cost_usd", 0.0),
            savings_pct=100.0,
            tokens_per_sec=d.get("tokens_per_sec", 0.0),
            baseline_model=d.get("baseline_model", "gpt-4o"),
        )
        self._saved_cost_usd += d.get("cost_usd", 0.0)
        return res

    def set(
        self,
        prompt: str,
        result: GenerationResult,
        model_id: str | None = None,
        priority: str | None = None,
        ttl_seconds: float | None = None,
    ) -> None:
        """Store a GenerationResult in cache."""
        if not self.enabled:
            return

        # Do not cache error responses
        if result.raw_error or "error" in result.text.lower()[:30]:
            return

        key = self._normalize_key(prompt, model_id, priority)

        # Evict oldest entry if capacity reached
        if len(self._memory_cache) >= self.max_entries:
            oldest_key = min(self._memory_cache.keys(), key=lambda k: self._memory_cache[k].created_at)
            del self._memory_cache[oldest_key]

        res_dict = {
            "text": result.text,
            "provider": result.provider,
            "model": result.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cost_usd": result.cost_usd,
            "latency_s": result.latency_s,
            "category": result.category,
            "complexity": result.complexity,
            "tokens_per_sec": result.tokens_per_sec,
            "baseline_model": result.baseline_model,
        }

        self._memory_cache[key] = CacheEntry(
            key_hash=key,
            result_dict=res_dict,
            created_at=time.time(),
            ttl_seconds=ttl_seconds or self.default_ttl,
        )
        self._save_to_disk()

    def clear(self) -> int:
        """Clear all in-memory and on-disk cache entries. Returns count cleared."""
        count = len(self._memory_cache)
        self._memory_cache.clear()
        try:
            if self._cache_file.exists():
                self._cache_file.unlink(missing_ok=True)
        except Exception:
            pass
        return count

    def stats(self) -> dict[str, Any]:
        """Return cache performance statistics."""
        total = self._hits + self._misses
        ratio = (self._hits / total * 100.0) if total > 0 else 0.0
        return {
            "entries": len(self._memory_cache),
            "hits": self._hits,
            "misses": self._misses,
            "hit_ratio_pct": round(ratio, 1),
            "saved_cost_usd": round(self._saved_cost_usd, 5),
            "enabled": self.enabled,
        }

    def print_stats_table(self) -> None:
        """Render a Rich table with cache metrics."""
        s = self.stats()
        table = Table(
            title="⚡ Sub-Millisecond Response Cache Performance",
            box=box.ROUNDED,
            header_style="bold cyan",
        )
        table.add_column("Metric", style="white")
        table.add_column("Value", style="bold green", justify="right")

        table.add_row("Status", "🟢 Active" if s["enabled"] else "🔴 Disabled")
        table.add_row("Cached Responses in Store", f"{s['entries']} entries")
        table.add_row("Cache Hits (sub-ms / $0)", f"{s['hits']}")
        table.add_row("Cache Misses", f"{s['misses']}")
        table.add_row("Hit Ratio", f"{s['hit_ratio_pct']}%")
        table.add_row("Total Cost Saved by Cache", f"${s['saved_cost_usd']:.4f}")

        console.print(table)
