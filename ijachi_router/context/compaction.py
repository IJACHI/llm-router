"""Context Compaction Engine for long-running sessions.

Document 3.5 (SC-04, SC-06):
- Triggers: context > 80% window, smaller model switch, /compact, or long session resume.
- Structured summary format:
  * goal
  * decisions and reasons
  * constraints and preferences
  * files changed and why
  * commands run and outcomes
  * errors and fixes
  * open tasks
  * unresolved questions
- Safety: full event log is never deleted on disk. Facts in ledger survive verbatim.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ijachi_router.session.events import CanonicalEvent
    from ijachi_router.session.state import SessionState


class CompactionEngine:
    """Produces structured summaries to fit long sessions into small context windows."""

    @staticmethod
    def compact_events(
        events: list["CanonicalEvent"],
        state: "SessionState",
        focus: str | None = None,
    ) -> str:
        """Create structured summary from prior events while preserving ledger facts verbatim."""
        # 1. Collect files changed
        files_changed = [
            f"{path} (modified)" for path, wf in state.working_set.items() if wf.modified_in_session
        ]

        # 2. Extract tool commands run and outcomes
        commands_run: list[str] = []
        errors_and_fixes: list[str] = []
        user_requests: list[str] = []

        for e in events:
            if e.type == "user_message":
                text = e.text_content
                if text:
                    user_requests.append(text[:200])
            elif e.type == "tool_call":
                tc = e.tool_call
                name = tc.get("name")
                args = tc.get("args", {})
                if name == "run_command" or name == "Bash":
                    cmd = args.get("command", "")
                    if cmd:
                        commands_run.append(f"`{cmd[:60]}`")
            elif e.type == "error":
                errors_and_fixes.append(e.text_content[:150])

        # 3. Build structured summary sections
        sections = [
            "# Structured Session Summary (Compacted)",
            f"\n## 1. Goal\n{focus or state.active_goal or (user_requests[0] if user_requests else 'Autonomous pairing session')}",
            "\n## 2. Decisions & Reasons (from Ledger)",
        ]

        # Invariant: facts in ledger MUST be included verbatim (SC-04)
        if state.ledger.entries:
            for entry in state.ledger.entries:
                sections.append(f"- [{entry.category}] {entry.fact}")
        else:
            sections.append("- No explicit architectural constraints recorded.")

        sections.append("\n## 3. Files Changed")
        if files_changed:
            for fc in files_changed[:20]:
                sections.append(f"- {fc}")
        else:
            sections.append("- No files modified yet.")

        sections.append("\n## 4. Commands Run & Outcomes")
        if commands_run:
            for cr in commands_run[-10:]:
                sections.append(f"- {cr}")
        else:
            sections.append("- None")

        if errors_and_fixes:
            sections.append("\n## 5. Errors and Fixes")
            for ef in errors_and_fixes[-5:]:
                sections.append(f"- {ef}")

        if state.plan_steps:
            sections.append("\n## 6. Open Tasks")
            for step in state.plan_steps:
                sections.append(f"- [{step.status}] {step.title}")

        summary_text = "\n".join(sections)
        state.rolling_summary = summary_text
        return summary_text


def compact_session_history(
    events: list["CanonicalEvent"],
    ledger: Any,
    state: Any = None,
    max_tokens: int = 1000,
) -> str:
    """Helper to compact session history while ensuring ledger entries survive verbatim."""
    from ijachi_router.session.state import SessionState
    if state is None:
        state = SessionState(session_id="compaction_session")
        if hasattr(ledger, "entries"):
            state.ledger = ledger
    return CompactionEngine.compact_events(events, state)
