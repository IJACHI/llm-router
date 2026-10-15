"""Routing explanation (/why) data structures and formatting.

Document 2.4 (FR-29) & Document 6.5:
Records every routing decision with:
- input signals (category, confidence, complexity, tools, session context)
- candidates filtered out and why
- ranked candidates with scores and estimated costs
- final decision, reasons (best fit, sticky bonus, escalation)
- actionable tips (e.g., /priority cost would choose X)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CandidateEvaluation:
    model_id: str
    provider: str
    score: float
    estimated_cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RoutingExplanation:
    category: str
    confidence: float
    complexity: float
    requires_tools: bool
    session_files_count: int
    current_model: str
    filtered_out: dict[str, str] = field(default_factory=dict)  # model -> reason
    ranked: list[CandidateEvaluation] = field(default_factory=list)
    chosen_model: str = ""
    chosen_provider: str = ""
    decision_reason: str = ""
    tip: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_signals": {
                "category": self.category,
                "confidence": self.confidence,
                "complexity": self.complexity,
                "requires_tools": self.requires_tools,
                "session_files_count": self.session_files_count,
                "current_model": self.current_model,
            },
            "filtered_out": self.filtered_out,
            "ranked": [c.to_dict() for c in self.ranked],
            "decision": {
                "chosen_model": f"{self.chosen_provider}/{self.chosen_model}",
                "reason": self.decision_reason,
            },
            "tip": self.tip,
        }

    def format_terminal_text(self) -> str:
        """Render beautiful /why terminal explanation according to Document 6.5."""
        lines = [
            "[bold cyan]Routing for the last turn[/bold cyan]",
            f"  [dim]Input signals[/dim]    category: [bold]{self.category}[/bold] ({self.confidence:.2f})  "
            f"complexity: [bold]{self.complexity:.2f}[/bold]  tools: [bold]{'yes' if self.requires_tools else 'no'}[/bold]",
            f"                   session: {self.session_files_count} files in play, current model: {self.current_model or 'none'}",
        ]

        if self.filtered_out:
            lines.append("  [dim]Filtered out[/dim]     " + "\n                   ".join(
                f"[yellow]{m}[/yellow] ({reason})" for m, reason in self.filtered_out.items()
            ))

        if self.ranked:
            lines.append("  [dim]Ranked[/dim]           " + "\n                   ".join(
                f"{i + 1}. [green]{c.provider}/{c.model_id}[/green] score {c.score:.2f} est ${c.estimated_cost_usd:.4f}"
                for i, c in enumerate(self.ranked[:5])
            ))

        lines.append(f"  [dim]Decision[/dim]         [bold green]{self.chosen_provider}/{self.chosen_model}[/bold green] ({self.decision_reason})")

        if self.tip:
            lines.append(f"  [dim]Tip[/dim]              [cyan]{self.tip}[/cyan]")

        return "\n".join(lines)


def generate_routing_explanation(**kwargs) -> RoutingExplanation:
    """Helper to instantiate RoutingExplanation with sensible defaults."""
    defaults = {
        "category": "code",
        "confidence": 0.95,
        "complexity": 0.4,
        "requires_tools": True,
        "session_files_count": 1,
        "current_model": "claude-3-5-sonnet",
        "chosen_model": "claude-3-5-sonnet",
        "chosen_provider": "anthropic",
        "decision_reason": "best fit with tool support",
    }
    defaults.update(kwargs)
    return RoutingExplanation(**defaults)
