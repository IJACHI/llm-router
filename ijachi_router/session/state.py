"""Session state and working set tracking for ijachi-llm-router.

Document 3.2, 3.10, SC-09:
Tracks working set (file content hashes and last-seen timestamps), active plan,
token and cost totals, pinned model, and budget caps.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ijachi_router.session.ledger import FactsAndDecisionsLedger


@dataclass
class WorkingFile:
    path: str
    sha256: str
    last_seen_ts: float
    modified_in_session: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkingFile:
        return cls(
            path=data.get("path", ""),
            sha256=data.get("sha256", ""),
            last_seen_ts=float(data.get("last_seen_ts", 0.0)),
            modified_in_session=bool(data.get("modified_in_session", False)),
        )


@dataclass
class PlanStep:
    id: int
    title: str
    status: str = "pending"  # pending | in_progress | completed | failed

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanStep:
        return cls(
            id=int(data.get("id", 0)),
            title=data.get("title", ""),
            status=data.get("status", "pending"),
        )


class SessionState:
    """In-memory representation of session state, persistent across turns."""

    def __init__(
        self,
        session_id: str,
        workspace_dir: str | Path | None = None,
        priority: str = "balanced",
        budget_usd: float | None = None,
        pinned_model: str | None = None,
    ):
        self.session_id = session_id
        self.workspace_dir = str(Path(workspace_dir or Path.cwd()).resolve())
        self.priority = priority
        self.budget_usd = budget_usd
        self.pinned_model = pinned_model
        self.current_model: str = ""
        self.current_provider: str = ""
        self.turn_count: int = 0
        self.total_cost_usd: float = 0.0
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.model_costs: dict[str, float] = {}
        self.working_set: dict[str, WorkingFile] = {}
        self.ledger: FactsAndDecisionsLedger = FactsAndDecisionsLedger()
        self.rolling_summary: str = ""
        self.active_goal: str = ""
        self.plan_steps: list[PlanStep] = []
        self.recent_categories: list[str] = []
        self.consecutive_tool_failures: int = 0
        self.tokens_cached_estimate: int = 0

    def compute_file_hash(self, path: str | Path) -> str | None:
        p = Path(path)
        if not p.is_absolute():
            p = (Path(self.workspace_dir) / p).resolve()
        if not p.exists() or not p.is_file():
            return None
        try:
            return hashlib.sha256(p.read_bytes()).hexdigest()
        except Exception:
            return None

    def record_file_read(self, path: str) -> None:
        h = self.compute_file_hash(path)
        import time
        self.working_set[path] = WorkingFile(
            path=path,
            sha256=h or "",
            last_seen_ts=time.time(),
            modified_in_session=False,
        )

    def record_file_write(self, path: str) -> None:
        h = self.compute_file_hash(path)
        import time
        self.working_set[path] = WorkingFile(
            path=path,
            sha256=h or "",
            last_seen_ts=time.time(),
            modified_in_session=True,
        )

    def check_stale_read(self, path: str) -> bool:
        """Check if file has changed on disk since it was recorded (FR-03)."""
        if path not in self.working_set:
            return False
        current_hash = self.compute_file_hash(path)
        return current_hash is not None and current_hash != self.working_set[path].sha256

    def record_usage(self, model: str, cost: float, in_tokens: int, out_tokens: int) -> None:
        self.total_cost_usd += cost
        self.total_input_tokens += in_tokens
        self.total_output_tokens += out_tokens
        self.model_costs[model] = self.model_costs.get(model, 0.0) + cost

    def is_budget_exceeded(self) -> bool:
        if self.budget_usd is not None and self.total_cost_usd >= self.budget_usd:
            return True
        return False

    @property
    def cost_ledger(self) -> dict[str, Any]:
        return {
            "call_count": self.turn_count,
            "total_cost_usd": self.total_cost_usd,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "model_costs": self.model_costs,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "workspace_dir": self.workspace_dir,
            "priority": self.priority,
            "budget_usd": self.budget_usd,
            "pinned_model": self.pinned_model,
            "current_model": self.current_model,
            "current_provider": self.current_provider,
            "turn_count": self.turn_count,
            "total_cost_usd": self.total_cost_usd,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "model_costs": self.model_costs,
            "working_set": {k: v.to_dict() for k, v in self.working_set.items()},
            "ledger": self.ledger.to_list(),
            "rolling_summary": self.rolling_summary,
            "active_goal": self.active_goal,
            "plan_steps": [s.to_dict() for s in self.plan_steps],
            "recent_categories": self.recent_categories[-10:],
            "consecutive_tool_failures": self.consecutive_tool_failures,
            "tokens_cached_estimate": self.tokens_cached_estimate,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionState:
        state = cls(
            session_id=data.get("session_id", ""),
            workspace_dir=data.get("workspace_dir", ""),
            priority=data.get("priority", "balanced"),
            budget_usd=data.get("budget_usd"),
            pinned_model=data.get("pinned_model"),
        )
        state.current_model = data.get("current_model", "")
        state.current_provider = data.get("current_provider", "")
        state.turn_count = int(data.get("turn_count", 0))
        state.total_cost_usd = float(data.get("total_cost_usd", 0.0))
        state.total_input_tokens = int(data.get("total_input_tokens", 0))
        state.total_output_tokens = int(data.get("total_output_tokens", 0))
        state.model_costs = data.get("model_costs") or {}
        state.working_set = {
            k: WorkingFile.from_dict(v) for k, v in (data.get("working_set") or {}).items()
        }
        state.ledger = FactsAndDecisionsLedger.from_list(data.get("ledger") or [])
        state.rolling_summary = data.get("rolling_summary", "")
        state.active_goal = data.get("active_goal", "")
        state.plan_steps = [PlanStep.from_dict(s) for s in (data.get("plan_steps") or [])]
        state.recent_categories = list(data.get("recent_categories") or [])
        state.consecutive_tool_failures = int(data.get("consecutive_tool_failures", 0))
        state.tokens_cached_estimate = int(data.get("tokens_cached_estimate", 0))
        return state
