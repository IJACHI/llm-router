"""Canonical event schema and models for ijachi-llm-router session continuity.

Document 3.3 Canonical event schema:
Events are versioned, append-only, and independent of any provider format.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CanonicalEvent:
    """A single canonical event in the session event log."""
    id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:8]}")
    session_id: str = ""
    ts: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    type: str = "user_message"  # user_message | assistant_message | tool_call | tool_result | route | error | compaction | checkpoint
    turn: int = 0
    model: dict[str, str] = field(default_factory=dict)  # {"provider": ..., "id": ...}
    content: list[dict[str, Any]] = field(default_factory=list)  # [{"kind": "text", "text": "..."}]
    tool_call: dict[str, Any] = field(default_factory=dict)  # {"id": "...", "name": "...", "args": {...}}
    usage: dict[str, Any] = field(default_factory=dict)  # {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cost_usd": 0.0}
    latency_ms: int = 0
    committed: bool = True
    schema: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CanonicalEvent:
        d = dict(data)
        return cls(
            id=d.get("id", f"evt_{uuid.uuid4().hex[:8]}"),
            session_id=d.get("session_id", ""),
            ts=d.get("ts", datetime.datetime.now(datetime.timezone.utc).isoformat()),
            type=d.get("type", "user_message"),
            turn=int(d.get("turn", 0)),
            model=d.get("model") or {},
            content=d.get("content") or [],
            tool_call=d.get("tool_call") or {},
            usage=d.get("usage") or {},
            latency_ms=int(d.get("latency_ms", 0)),
            committed=bool(d.get("committed", True)),
            schema=int(d.get("schema", 1)),
        )

    @property
    def text_content(self) -> str:
        """Extract concatenated text content from content parts."""
        parts = []
        for part in self.content:
            if isinstance(part, dict) and part.get("kind") == "text":
                parts.append(str(part.get("text", "")))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)

    @classmethod
    def create_user_message(cls, text: str, session_id: str = "") -> CanonicalEvent:
        return cls(
            type="user_message",
            session_id=session_id,
            content=[{"kind": "text", "text": text}],
            committed=True,
        )

    @classmethod
    def create_assistant_message(
        cls,
        text: str,
        session_id: str = "",
        model: dict[str, str] | None = None,
        usage: dict[str, Any] | None = None,
        latency_ms: int = 0,
    ) -> CanonicalEvent:
        return cls(
            type="assistant_message",
            session_id=session_id,
            content=[{"kind": "text", "text": text}],
            model=model or {},
            usage=usage or {},
            latency_ms=latency_ms,
            committed=True,
        )

    @classmethod
    def create_tool_call(cls, name: str, args: dict[str, Any], session_id: str = "") -> CanonicalEvent:
        return cls(
            type="tool_call",
            session_id=session_id,
            tool_call={"id": f"call_{uuid.uuid4().hex[:8]}", "name": name, "args": args},
            committed=True,
        )

    @classmethod
    def create_tool_result(cls, call_id: str, output: str, session_id: str = "", success: bool = True) -> CanonicalEvent:
        return cls(
            type="tool_result",
            session_id=session_id,
            content=[{"kind": "text", "text": output}],
            tool_call={"id": call_id, "success": success},
            committed=True,
        )
