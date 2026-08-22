"""Three-Layer Context Memory Manager for ijachi-llm-router.

Coordinates and unifies:
  - Layer 1 (L1) Global Memory: Cross-session persistent memory stored on disk (ProjectMemory).
  - Layer 2 (L2) Session Memory: Session-scoped objectives, progress milestones, and model switch events.
  - Layer 3 (L3) Task Ring Buffer: Intra-session context across sequential tasks/turns.

Generates a unified token-bounded context prompt block to inject before each LLM task execution.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ijachi_router.memory import ProjectMemory


@dataclass
class TaskTurn:
    """A record of a single task execution within the active session."""
    task: str
    summary: str
    model: str
    cost_usd: float = 0.0
    timestamp: float = field(default_factory=time.time)


class ContextManager:
    """Orchestrates L1 (Global), L2 (Session), and L3 (Task) context memory layers."""

    def __init__(
        self,
        root_dir: Path | str | None = None,
        max_l3_turns: int = 5,
        memory_dir: Path | str | None = None,
    ):
        self.root_dir = Path(root_dir or Path.cwd()).resolve()
        self.project_name = self.root_dir.name
        self.max_l3_turns = max_l3_turns

        # Layer 1: Persistent Global Disk Memory
        self.l1_global = ProjectMemory(root_dir=self.root_dir, memory_dir=memory_dir)

        # Layer 2: Session-scoped Memory (Survives model switches, resets per interactive session)
        self.session_goal: str = ""
        self.session_milestones: list[str] = []
        self.session_model_switches: list[dict[str, Any]] = []
        self.session_start_time: float = time.time()

        # Layer 3: Task Ring Buffer (Recent turn context)
        self.l3_task_turns: list[TaskTurn] = []

    # ------------------------------------------------------------------
    # L2: Session Management
    # ------------------------------------------------------------------

    def set_session_goal(self, goal: str, auto: bool = False) -> None:
        """Set or update the active session's overarching goal.
        
        Args:
            goal: The task/objective description.
            auto: True if auto-detected from the first user turn.
        """
        clean_goal = goal.strip()
        if not clean_goal:
            return
        if auto and self.session_goal:
            # If already set, do not overwrite automatic goal
            return
        self.session_goal = clean_goal

    def record_model_switch(self, from_model: str, to_model: str, reason: str = "user switched model") -> None:
        """Record a model switch so incoming models maintain context hand-off."""
        switch_event = {
            "from": from_model or "auto",
            "to": to_model or "auto",
            "reason": reason,
            "time": time.time(),
        }
        self.session_model_switches.append(switch_event)
        # Also notify L1 for global persistence
        self.l1_global.record_model_switch(from_model, to_model, reason)

    def add_milestone(self, milestone: str) -> None:
        """Record a key milestone accomplished during this session."""
        if milestone and milestone not in self.session_milestones:
            self.session_milestones.append(milestone)

    # ------------------------------------------------------------------
    # L3: Task Ring Buffer & Turn Recording
    # ------------------------------------------------------------------

    def record_task(
        self,
        task: str,
        result_text: str,
        model: str,
        cost_usd: float = 0.0,
    ) -> None:
        """Record a completed task across all 3 layers.
        
        - Appends to L3 task ring buffer.
        - Compresses oldest turns into L1 global memory when limit exceeded.
        - Updates L2 session milestones.
        """
        # Form a concise summary
        summary = result_text.strip().replace("\n", " ")[:250]
        if len(result_text.strip()) > 250:
            summary += "..."

        turn = TaskTurn(
            task=task.strip(),
            summary=summary,
            model=model,
            cost_usd=cost_usd,
        )
        self.l3_task_turns.append(turn)

        # Set default session goal from first task if not explicitly set
        if not self.session_goal:
            self.set_session_goal(task, auto=True)

        # Add milestone for significant actions
        self.add_milestone(f"Completed '{task[:60]}' using {model}")

        # Sync to L1 global storage
        self.l1_global.add_turn(
            task=task,
            response_text=result_text,
            model=model,
            cost_usd=cost_usd,
        )

        # Enforce L3 ring buffer size limit
        if len(self.l3_task_turns) > self.max_l3_turns:
            self.l3_task_turns.pop(0)

    # ------------------------------------------------------------------
    # Context Block Generation
    # ------------------------------------------------------------------

    def build_context_block(self, current_task: str = "") -> str:
        """Build the structured, unified context prompt block.
        
        Returns empty string if there is no memory to inject.
        """
        sections: list[str] = []

        # 1. L1 Global Context (Architecture decisions, preferences, past session digest)
        l1_block = self.l1_global.get_l1_context(max_tokens=300)
        if l1_block.strip():
            sections.append(f"### [Layer 1: Project & Historical Memory]\n{l1_block.strip()}")

        # 2. L2 Session Context (Session goal, progress, recent model hand-offs)
        l2_parts: list[str] = []
        if self.session_goal:
            l2_parts.append(f"Current Session Goal: {self.session_goal}")
        if self.session_milestones:
            recent_milestones = self.session_milestones[-4:]
            l2_parts.append("Session Milestones:\n" + "\n".join(f"  ✓ {m}" for m in recent_milestones))
        if self.session_model_switches:
            last_switch = self.session_model_switches[-1]
            l2_parts.append(f"Model Transition: Handed off from {last_switch['from']} -> {last_switch['to']}")

        if l2_parts:
            sections.append(f"### [Layer 2: Active Session & Intent]\n" + "\n".join(l2_parts))

        # 3. L3 Recent Tasks Buffer (Immediate conversational turns in session)
        if self.l3_task_turns:
            l3_lines = []
            for i, t in enumerate(self.l3_task_turns[-3:], start=1):
                l3_lines.append(f"  {i}. Task: \"{t.task}\" -> Done: {t.summary} (model: {t.model})")
            sections.append(f"### [Layer 3: Recent Tasks Context]\n" + "\n".join(l3_lines))

        if not sections:
            return ""

        joined_sections = "\n\n".join(sections)
        return (
            "--- IJACHI CONTEXT & PERSISTENT MEMORY ---\n"
            "Use the following multi-layer context to maintain continuity, project conventions, and previous progress:\n\n"
            f"{joined_sections}\n"
            "--- END CONTEXT ---"
        )

    # ------------------------------------------------------------------
    # Utilities & Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist L1 state to disk."""
        self.l1_global.save()

    def clear(self) -> None:
        """Reset all context layers (L1 disk, L2 session, L3 tasks)."""
        self.l1_global.clear()
        self.session_goal = ""
        self.session_milestones = []
        self.session_model_switches = []
        self.l3_task_turns = []

    def summary(self) -> str:
        """Return human-readable multi-layer memory summary."""
        l1_summary = self.l1_global.summary()
        return (
            f"=== 🧠 Context Memory Status ===\n"
            f"L1 Global Memory:\n{l1_summary}\n"
            f"L2 Session Goal: {self.session_goal or '(None set)'}\n"
            f"L2 Milestones Recorded: {len(self.session_milestones)}\n"
            f"L2 Model Switches: {len(self.session_model_switches)}\n"
            f"L3 Active Task Turns: {len(self.l3_task_turns)}/{self.max_l3_turns}\n"
        )
