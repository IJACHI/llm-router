"""Monthly Budget Alerts & Hard Spend Cap Manager for ijachi-llm-router.

Tracks monthly USD spend across all model providers and enforces budget caps,
automatically failing over to 100% free offline Ollama when limits are reached.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_BUDGET_FILE = Path.home() / ".ijachi-llmr" / "budget.json"


@dataclass
class BudgetConfig:
    monthly_limit_usd: float = 20.0
    current_month: str = ""
    accumulated_spend_usd: float = 0.0
    auto_failover_ollama: bool = True

    @property
    def percentage_used(self) -> float:
        if self.monthly_limit_usd <= 0:
            return 0.0
        return (self.accumulated_spend_usd / self.monthly_limit_usd) * 100.0


class BudgetManager:
    """Manages monthly USD budget configuration and spend enforcement."""

    def __init__(self, budget_file: Path | str | None = None):
        self.budget_file = Path(budget_file or _BUDGET_FILE)
        self.config = self.load()

    def load(self) -> BudgetConfig:
        current_m = datetime.now().strftime("%Y-%m")
        if not self.budget_file.exists():
            return BudgetConfig(monthly_limit_usd=20.0, current_month=current_m, accumulated_spend_usd=0.0)
        try:
            data = json.loads(self.budget_file.read_text(encoding="utf-8"))
            if data.get("current_month") != current_m:
                # New month — reset accumulated spend
                data["current_month"] = current_m
                data["accumulated_spend_usd"] = 0.0
            return BudgetConfig(**data)
        except Exception:
            return BudgetConfig(monthly_limit_usd=20.0, current_month=current_m, accumulated_spend_usd=0.0)

    def save(self) -> None:
        self.budget_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "monthly_limit_usd": self.config.monthly_limit_usd,
            "current_month": self.config.current_month,
            "accumulated_spend_usd": round(self.config.accumulated_spend_usd, 6),
            "auto_failover_ollama": self.config.auto_failover_ollama,
        }
        self.budget_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def record_spend(self, cost_usd: float) -> None:
        self.config.accumulated_spend_usd += cost_usd
        self.save()

    def set_budget(self, limit_usd: float) -> None:
        self.config.monthly_limit_usd = limit_usd
        self.save()

    def check_budget_status(self) -> tuple[bool, str]:
        """Returns (is_exceeded: bool, message: str)."""
        pct = self.config.percentage_used
        spend = self.config.accumulated_spend_usd
        limit = self.config.monthly_limit_usd

        if spend >= limit:
            return True, f"⚠ Monthly budget hard cap of ${limit:.2f} reached (${spend:.2f} spent). Failover active."
        elif pct >= 80.0:
            return False, f"⚠️ Warning: {pct:.1f}% of monthly budget used (${spend:.2f} / ${limit:.2f})."
        
        return False, f"✓ Budget OK: ${spend:.2f} / ${limit:.2f} ({pct:.1f}% used)."

    def summary(self) -> str:
        _, msg = self.check_budget_status()
        return (
            f"Monthly Budget Status ({self.config.current_month}):\n"
            f"  • Monthly Limit: ${self.config.monthly_limit_usd:.2f}\n"
            f"  • Accumulated Spend: ${self.config.accumulated_spend_usd:.4f}\n"
            f"  • Budget Used: {self.config.percentage_used:.1f}%\n"
            f"  • {msg}\n"
        )
