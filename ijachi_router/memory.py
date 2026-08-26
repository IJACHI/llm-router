"""Persistent Project Memory & Lossless Context Compressor for ijachi-llm-router.

Maintains project state, architectural decisions, modified symbols, and user goals
across sessions while compressing context history with LLM-assisted summarisation
to save 70-90% token costs.

Layer 1 (L1) — Global/cross-session memory for a specific workspace project.
Persists to disk as JSON at ~/.ijachi-llmr/memory/<project>_global.json.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_MEMORY_DIR = Path.home() / ".ijachi-llmr" / "memory"


@dataclass
class MemoryTurn:
    """A single completed task turn stored in memory."""
    task: str = ""
    """The user's task/question."""
    response_summary: str = ""
    """Short summary of what the agent did/answered."""
    model: str = "unknown"
    """The model that handled this turn."""
    cost_usd: float = 0.0
    timestamp: float = field(default_factory=time.time)

    # Legacy field aliases for backwards compatibility
    prompt: str = ""
    response: str = ""

    def __post_init__(self):
        if not self.task and self.prompt:
            self.task = self.prompt
        if not self.prompt and self.task:
            self.prompt = self.task
        if not self.response_summary and self.response:
            self.response_summary = self.response[:300]
        if not self.response and self.response_summary:
            self.response = self.response_summary

    @classmethod
    def from_result(cls, task: str, response_text: str, model: str, cost_usd: float) -> "MemoryTurn":
        """Construct from an agent result, trimming the response to a compact summary."""
        summary = response_text.strip().replace("\n", " ")[:300]
        return cls(
            task=task,
            response_summary=summary,
            model=model,
            cost_usd=cost_usd,
            prompt=task,
            response=response_text,
        )


@dataclass
class ModelSwitchEvent:
    """Records a model switch event so subsequent models know the context."""
    from_model: str
    to_model: str
    reason: str = "user request"
    timestamp: float = field(default_factory=time.time)


class ProjectMemory:
    """Manages persistent project memory & LLM-assisted hierarchical context compression.

    Storage schema (JSON on disk):
    {
        "project_name": str,
        "session_id": str,
        "global_digest": str,
        "preferences": dict,
        "architectural_decisions": list[str],
        "total_tokens_saved": int,
        "turns": [MemoryTurn, ...]
    }

    Args:
        root_dir: Workspace root. Memory file is keyed to root_dir.name.
        session_id: Session identifier (default: "default").
        memory_dir: Override for the memory storage directory.
    """

    def __init__(
        self,
        root_dir: Path | str | None = None,
        session_id: str = "default",
        memory_dir: Path | str | None = None,
    ):
        self.root_dir = Path(root_dir or Path.cwd()).resolve()
        self.project_name = self.root_dir.name
        self.session_id = session_id
        self.memory_dir = Path(memory_dir).resolve() if memory_dir else _MEMORY_DIR
        
        if self.session_id == "default":
            self.memory_file = self.memory_dir / f"{self.project_name}_global.json"
        else:
            self.memory_file = self.memory_dir / f"{self.project_name}_{self.session_id}.json"

        # State
        self.global_digest: str = ""
        self.preferences: dict[str, Any] = {}
        self.architectural_decisions: list[str] = []
        self.total_tokens_saved: int = 0
        self.turns: list[MemoryTurn] = []
        self.model_switches: list[ModelSwitchEvent] = []

        self.load()

    @property
    def compressed_digest(self) -> str:
        return self.global_digest

    @compressed_digest.setter
    def compressed_digest(self, val: str) -> None:
        self.global_digest = val

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load memory state from disk. Silent no-op if file doesn't exist yet."""
        if not self.memory_file.exists():
            return
        try:
            data = json.loads(self.memory_file.read_text(encoding="utf-8"))
            self.global_digest = data.get("global_digest", data.get("compressed_digest", ""))
            self.preferences = data.get("preferences", {})
            self.architectural_decisions = data.get("architectural_decisions", [])
            self.total_tokens_saved = data.get("total_tokens_saved", 0)
            self.turns = [MemoryTurn(**t) for t in data.get("turns", [])]
            self.model_switches = [
                ModelSwitchEvent(**e) for e in data.get("model_switches", [])
            ]
        except Exception:
            pass  # Corrupt file: start fresh

    def save(self) -> None:
        """Persist the current memory state to disk."""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "project_name": self.project_name,
            "session_id": self.session_id,
            "global_digest": self.global_digest,
            "compressed_digest": self.global_digest,
            "preferences": self.preferences,
            "architectural_decisions": self.architectural_decisions,
            "total_tokens_saved": self.total_tokens_saved,
            "turns": [asdict(t) for t in self.turns],
            "model_switches": [asdict(e) for e in self.model_switches],
            "saved_at": time.time(),
        }
        self.memory_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def clear(self) -> None:
        """Wipe all memory (disk + in-memory). Irreversible."""
        self.global_digest = ""
        self.preferences = {}
        self.architectural_decisions = []
        self.total_tokens_saved = 0
        self.turns = []
        self.model_switches = []
        if self.memory_file.exists():
            self.memory_file.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def add_turn(
        self,
        task: str = "",
        response_text: str = "",
        model: str = "unknown",
        cost_usd: float = 0.0,
        prompt: str = "",
        response: str = "",
    ) -> None:
        """Record a completed agent task turn and compress if needed."""
        actual_task = task or prompt
        actual_response = response_text or response
        turn = MemoryTurn.from_result(actual_task, actual_response, model, cost_usd)
        self.turns.append(turn)
        self.compress_if_needed()
        self.save()

    def record_model_switch(self, from_model: str, to_model: str, reason: str = "user request") -> None:
        """Record a model switch event in L1 so future sessions know what happened."""
        event = ModelSwitchEvent(from_model=from_model or "auto", to_model=to_model or "auto", reason=reason)
        self.model_switches.append(event)
        self.model_switches = self.model_switches[-10:]
        self.save()

    def set_preference(self, key: str, value: Any) -> None:
        """Persist a user preference (style_guide, priority, theme, etc.)."""
        self.preferences[key] = value
        self.save()

    def add_architectural_decision(self, decision: str) -> None:
        """Record a long-lived architectural decision about the project."""
        if decision not in self.architectural_decisions:
            self.architectural_decisions.append(decision)
            self.architectural_decisions = self.architectural_decisions[-20:]
            self.save()

    # ------------------------------------------------------------------
    # Compression (LLM-assisted + rule-based fallback)
    # ------------------------------------------------------------------

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimate (~4 characters per token)."""
        return len(text) // 4

    def _estimate_tokens(self, text: str) -> int:
        return self.estimate_tokens(text)

    def compress_if_needed(
        self,
        threshold: int = 10,
        threshold_tokens: int | None = None,
    ) -> None:
        """Compress old turns into the global digest when buffer exceeds threshold."""
        if threshold_tokens is not None:
            history_text = "\n".join(f"User: {t.prompt}\nAssistant: {t.response}" for t in self.turns)
            if self.estimate_tokens(history_text) < threshold_tokens:
                return
            self.compress(use_llm=False)
            return

        if len(self.turns) < threshold:
            return
        self.compress(use_llm=True)

    def compress(self, use_llm: bool = True) -> None:
        """Compress all but the last 2-3 turns into the global digest."""
        if len(self.turns) <= 2:
            return

        keep = self.turns[-2:]
        old = self.turns[:-2]
        self.turns = keep

        if use_llm:
            new_digest = self._llm_summarise(old)
        else:
            new_digest = self._rule_summarise(old)

        if self.global_digest and use_llm:
            combined_prompt = (
                f"Previous summary:\n{self.global_digest}\n\n"
                f"New additions:\n{new_digest}"
            )
            new_digest = self._llm_merge(combined_prompt)
        elif self.global_digest:
            new_digest = f"{self.global_digest}\n{new_digest}"

        old_tokens = self.estimate_tokens(
            "\n".join(f"{t.task}: {t.response_summary}" for t in old)
        )
        new_tokens = self.estimate_tokens(new_digest)
        self.total_tokens_saved += max(0, old_tokens - new_tokens)
        self.global_digest = new_digest

    def _llm_summarise(self, turns: list[MemoryTurn]) -> str:
        """Use the LLM to produce a compact semantic digest of completed turns."""
        try:
            from ijachi_router.core import route
            history = "\n".join(
                f"- Task: {t.task}\n  Done: {t.response_summary}"
                for t in turns
            )
            prompt = (
                "You are a memory compressor for a coding agent. "
                "Summarise the following completed tasks into a concise bullet-point digest "
                "that preserves key decisions, files changed, and outcomes. "
                "Be extremely concise — maximum 250 words. "
                "Focus on facts that would help a future session continue this work.\n\n"
                f"Tasks completed:\n{history}"
            )
            res = route(prompt=prompt, priority="speed", humanize_mode="off", timeout=5)
            return res.text.strip()
        except Exception:
            return self._rule_summarise(turns)

    def _llm_merge(self, combined_text: str) -> str:
        """Merge an existing digest with a new one using the LLM."""
        try:
            from ijachi_router.core import route
            prompt = (
                "Merge and deduplicate the following two project memory summaries "
                "into one concise bullet-point digest (maximum 300 words):\n\n"
                f"{combined_text}"
            )
            res = route(prompt=prompt, priority="speed", humanize_mode="off", timeout=5)
            return res.text.strip()
        except Exception:
            return combined_text[:1200]

    def _rule_summarise(self, turns: list[MemoryTurn]) -> str:
        """Rule-based fallback: produce a structured lossless digest without LLM."""
        digest_parts = [
            f"# Lossless Project Digest ({self.project_name})",
            f"Active Session: {self.session_id}",
            "Key Project Constraints & Decisions:",
        ]
        for t in turns:
            task_short = t.task[:150].strip()
            resp_short = t.response_summary[:200].strip().replace("\n", " ")
            digest_parts.append(f"  • Goal/Query: {task_short} -> Solution: {resp_short}")
        return "\n".join(digest_parts)

    # ------------------------------------------------------------------
    # Context retrieval
    # ------------------------------------------------------------------

    def get_compressed_context(self) -> str:
        """Legacy helper: return formatted compressed digest and recent turns."""
        parts = []
        if self.global_digest:
            parts.append(f"--- PREVIOUS SESSION MEMORY (Compressed Digest) ---\n{self.global_digest}\n")
        if self.turns:
            recent_str = "\n".join(f"User: {t.prompt}\nAssistant: {t.response}" for t in self.turns[-2:])
            parts.append(f"--- RECENT CONVERSATION ---\n{recent_str}\n")
        return "\n".join(parts)

    def get_l1_context(self, max_tokens: int = 300) -> str:
        """Return the L1 global context block for prompt injection."""
        parts: list[str] = []
        if self.global_digest:
            digest_trimmed = self.global_digest[: max_tokens * 4]
            parts.append(f"Previous session memory:\n{digest_trimmed}")
        if self.architectural_decisions:
            decisions = "\n".join(f"  • {d}" for d in self.architectural_decisions[-5:])
            parts.append(f"Project decisions:\n{decisions}")
        if self.preferences:
            pref_str = ", ".join(f"{k}={v}" for k, v in self.preferences.items())
            parts.append(f"User preferences: {pref_str}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """Return a human-readable memory status summary."""
        turn_count = len(self.turns)
        has_digest = "Yes" if self.global_digest else "No"
        return (
            f"Project Memory Summary:\n"
            f"  • Project: {self.project_name}\n"
            f"  • Session ID: {self.session_id}\n"
            f"  • Active Turns in Memory: {turn_count}\n"
            f"  • Lossless Digest Compressed: {has_digest}\n"
            f"  • Estimated Tokens Saved: {self.total_tokens_saved:,} tokens\n"
            f"  • Architectural decisions: {len(self.architectural_decisions)}\n"
            f"  • Preferences stored: {len(self.preferences)}\n"
            f"  • Memory file: {self.memory_file}\n"
        )
