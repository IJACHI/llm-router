"""Learned routing: per-(model, category) success records that adjust candidate scores.

Evidence comes from evaluation runs (ground truth, weight 1.0) and from ordinary agent turns
(weak signal, weight 0.25: success = finished without hitting a limit, a loop, or
escalation). The bonus is a shrunk success-rate estimate centred on 0, bounded to +/-0.15
so it nudges ranking without overriding policy, price or quality tiers.

Disable with IJACHI_LEARNED_ROUTING=0.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

OUTCOMES_PATH = Path.home() / ".ijachi-llmr" / "outcomes.json"
_MAX_BONUS = 0.15
_PRIOR_WEIGHT = 4.0   # pseudo-observations pulling estimates toward "unknown"
_MIN_EVIDENCE = 2.0   # below this, no adjustment

_lock = threading.Lock()
_cache: dict | None = None


def _base(category: str) -> str:
    return "code" if category in ("debugging", "code-edit/refactor") else category


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(OUTCOMES_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _cache = {}
    return _cache


def enabled() -> bool:
    return os.environ.get("IJACHI_LEARNED_ROUTING", "1").strip().lower() not in ("0", "false", "off", "no")


def record(model_key: str, category: str, success: bool, weight: float = 1.0, path: Path | None = None) -> None:
    global _cache
    target = path or OUTCOMES_PATH
    with _lock:
        data = _load() if path is None else (json.loads(target.read_text()) if target.exists() else {})
        cell = data.setdefault(model_key, {}).setdefault(_base(category), {"s": 0.0, "f": 0.0})
        cell["s" if success else "f"] += weight
        cell["t"] = int(time.time())
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, target)
        if path is None:
            _cache = data


def bonus(model_key: str, category: str) -> float:
    """Score adjustment in [-0.15, 0.15] from recorded outcomes (0 when unknown/disabled)."""
    if not enabled():
        return 0.0
    cell = _load().get(model_key, {}).get(_base(category))
    if not cell:
        return 0.0
    s, f = float(cell.get("s", 0)), float(cell.get("f", 0))
    if s + f < _MIN_EVIDENCE:
        return 0.0
    rate = (s + 0.5 * _PRIOR_WEIGHT) / (s + f + _PRIOR_WEIGHT)  # shrunk toward 0.5
    return max(-_MAX_BONUS, min(_MAX_BONUS, (rate - 0.5) * 2 * _MAX_BONUS))


def summary() -> dict:
    return _load()


def reset_cache() -> None:
    global _cache
    _cache = None
