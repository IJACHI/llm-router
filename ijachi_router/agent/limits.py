"""Agent loop limits, cost cap enforcement, and repetition detection.

Document 2.3 (FR-07, FR-08):
- Enforce max tool iterations per user message (default 50)
- Per-turn and per-session cost caps
- Repetition detection: detect identical tool call and result 3 times and stop with diagnostic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LoopLimits:
    max_turns: int = 50
    max_cost_per_turn_usd: float | None = None
    session_budget_usd: float | None = None
    timeout_sec: int = 300


class RepetitionDetector:
    """Detects infinite loops where the model issues the same tool call and gets the same output 3 times."""

    def __init__(self, threshold: int = 3):
        self.threshold = threshold
        self.history: list[tuple[str, str]] = []

    def record_call_and_result(self, tool_name: str, args: dict[str, Any], output: str) -> bool:
        """Record a tool invocation. Returns True if repetition loop is detected."""
        key = f"{tool_name}:{json.dumps(args, sort_keys=True)}"
        out_summary = output[:300].strip()
        pair = (key, out_summary)

        self.history.append(pair)
        if len(self.history) >= self.threshold:
            # Check last N
            last_n = self.history[-self.threshold:]
            if all(p == pair for p in last_n):
                return True
        return False
