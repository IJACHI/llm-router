"""Facts and decisions ledger for session continuity.

Document 3.2 & SC-04:
Short pinned entries: user constraints, chosen approaches, names, versions, rejected options.
The facts and decisions ledger MUST survive compaction verbatim.
"""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class LedgerEntry:
    category: str  # constraint | decision | preference | naming | rejected_option | file_note
    fact: str
    added_turn: int = 0
    ts: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LedgerEntry:
        return cls(
            category=data.get("category", "fact"),
            fact=data.get("fact", ""),
            added_turn=int(data.get("added_turn", 0)),
            ts=data.get("ts", ""),
        )


class FactsAndDecisionsLedger:
    """Stores pinned facts and decisions that survive any context compaction."""

    def __init__(self, entries: list[LedgerEntry] | None = None):
        self.entries: list[LedgerEntry] = list(entries or [])

    def record_fact(self, fact: str, category: str = "decision", turn: int = 0) -> None:
        """Add a new fact or constraint if not already recorded."""
        fact_clean = fact.strip()
        if not fact_clean:
            return
        for e in self.entries:
            if e.fact.lower() == fact_clean.lower():
                return
        self.entries.append(LedgerEntry(category=category, fact=fact_clean, added_turn=turn))

    def record_decision(self, decision: str, turn: int = 0) -> None:
        """Add a decision to the ledger."""
        self.record_fact(decision, category="decision", turn=turn)

    def format_for_context(self) -> str:
        """Render ledger entries for system prompt injection."""
        if not self.entries:
            return ""
        lines = ["[Facts and Decisions Ledger]"]
        for e in self.entries:
            lines.append(f"- [{e.category}] {e.fact}")
        return "\n".join(lines)

    def to_list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.entries]

    @classmethod
    def from_list(cls, data: list[dict[str, Any]]) -> FactsAndDecisionsLedger:
        return cls([LedgerEntry.from_dict(d) for d in data])
