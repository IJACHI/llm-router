"""Context Assembler: builds model-specific requests within token budget.

Document 3.4 (SC-05, SC-10):
1. Usable input budget: B = 0.75 * W - O
2. Priority layers:
   Layer 1: System prompt (core + provider overlay)
   Layer 2: Tool definitions
   Layer 3: Project memory (IJACHI.md)
   Layer 4: Facts and decisions ledger
   Layer 5: Current plan
   Layer 6: Rolling summary
   Layer 7: Recent turns verbatim (newest first)
   Layer 8: Retrieved tool results & file snippets
   Layer 9: New user message
3. Token tracking per layer for /context visualization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ijachi_router.context.compaction import CompactionEngine
from ijachi_router.context.memory import load_project_memory
from ijachi_router.context.tokens import estimate_tokens

if TYPE_CHECKING:
    from ijachi_router.session.events import CanonicalEvent
    from ijachi_router.session.state import SessionState


@dataclass
class LayerTokens:
    system_prompt: int = 0
    tools: int = 0
    project_memory: int = 0
    ledger: int = 0
    plan: int = 0
    summary: int = 0
    recent_turns: int = 0
    tool_results: int = 0
    user_message: int = 0

    @property
    def total(self) -> int:
        return (
            self.system_prompt
            + self.tools
            + self.project_memory
            + self.ledger
            + self.plan
            + self.summary
            + self.recent_turns
            + self.tool_results
            + self.user_message
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "System Prompt": self.system_prompt,
            "Tool Schemas": self.tools,
            "Project Memory (IJACHI.md)": self.project_memory,
            "Facts & Ledger": self.ledger,
            "Active Plan": self.plan,
            "Rolling Summary": self.summary,
            "Recent Turns": self.recent_turns,
            "Tool Results": self.tool_results,
            "User Message": self.user_message,
        }


@dataclass
class AssembledContext:
    system_prompt: str
    messages: list[dict[str, Any]]
    layers: LayerTokens
    total_tokens: int
    budget: int
    model_window: int


_CORE_SYSTEM_PROMPT = """You are ijachi-code, an elite terminal coding assistant with full session continuity.
You have access to local workspace tools. Use tools to inspect files, execute commands, and apply code edits.
Always be accurate, direct, concise, and respect project memory and safety permissions.
"""

_DEFAULT_TOOLS_DESCRIPTION = """Available tools:
- Read(path, start_line, end_line): Read lines from a workspace file
- Edit(path, target_content, replacement_content): Atomically edit file content
- Write(path, content): Create or overwrite a file
- Glob(pattern): Find files matching a glob pattern
- Grep(query, path): Search file content with regular expression
- ListDir(path): List directory entries
- Bash(command): Execute a sandboxed shell command
- Plan(action, steps): Update goal and task steps
"""


class ContextAssembler:
    """Assembles prompt layers tailored to the candidate model's context budget."""

    def __init__(self, workspace_dir: Path | str | None = None):
        self.workspace_dir = Path(workspace_dir or Path.cwd()).resolve()

    def assemble(
        self,
        state: "SessionState",
        events: list["CanonicalEvent"],
        new_user_message: str,
        model_window: int = 128_000,
        reserved_output: int = 4_096,
        provider_name: str = "default",
    ) -> AssembledContext:
        """Assemble context layers enforcing B = 0.75 * W - O budget."""
        budget = int(0.75 * model_window - reserved_output)
        if budget < 1000:
            budget = 1000

        layer_tokens = LayerTokens()

        # Layer 1: System prompt
        sys_prompt = _CORE_SYSTEM_PROMPT
        layer_tokens.system_prompt = estimate_tokens(sys_prompt, provider_name)

        # Layer 2: Tool descriptions / schemas
        tools_desc = _DEFAULT_TOOLS_DESCRIPTION
        layer_tokens.tools = estimate_tokens(tools_desc, provider_name)

        # Layer 3: Project memory (IJACHI.md)
        proj_mem = load_project_memory(self.workspace_dir)
        layer_tokens.project_memory = estimate_tokens(proj_mem, provider_name)

        # Layer 4: Ledger (survives compaction verbatim)
        ledger_text = state.ledger.format_for_context()
        layer_tokens.ledger = estimate_tokens(ledger_text, provider_name)

        # Layer 5: Plan
        plan_text = ""
        if state.plan_steps:
            p_lines = ["[Active Execution Plan]"]
            for step in state.plan_steps:
                p_lines.append(f"{step.id}. [{step.status}] {step.title}")
            plan_text = "\n".join(p_lines)
            layer_tokens.plan = estimate_tokens(plan_text, provider_name)

        # Layer 9: New user message (must never be dropped)
        layer_tokens.user_message = estimate_tokens(new_user_message, provider_name)

        # Mandatory base tokens
        mandatory_tokens = (
            layer_tokens.system_prompt
            + layer_tokens.tools
            + layer_tokens.project_memory
            + layer_tokens.ledger
            + layer_tokens.plan
            + layer_tokens.user_message
        )

        remaining_budget = budget - mandatory_tokens

        # Check if compaction is needed (or if already summarized)
        summary_text = state.rolling_summary
        if len(events) > 10 and (not summary_text or remaining_budget < 2000):
            summary_text = CompactionEngine.compact_events(events, state)
        layer_tokens.summary = estimate_tokens(summary_text, provider_name)
        remaining_budget -= layer_tokens.summary

        # Layer 7 & 8: Recent turns verbatim and tool results
        messages: list[dict[str, Any]] = []

        # Build combined system instructions
        system_blocks = [sys_prompt, tools_desc]
        if proj_mem:
            system_blocks.append(proj_mem)
        if ledger_text:
            system_blocks.append(ledger_text)
        if plan_text:
            system_blocks.append(plan_text)
        if summary_text:
            system_blocks.append(summary_text)

        full_system_text = "\n\n".join(system_blocks)

        # Pack recent events newest first until remaining budget exhausted
        recent_messages: list[dict[str, Any]] = []
        recent_toks = 0
        tool_toks = 0

        # We take committed events in reverse order
        committed_events = [e for e in events if e.committed]
        for e in reversed(committed_events):
            role = "user" if e.type == "user_message" else "assistant"
            content = e.text_content

            if e.type == "tool_call":
                role = "assistant"
                content = f"Tool Call: {e.tool_call.get('name')}({e.tool_call.get('args')})"
            elif e.type == "tool_result":
                role = "user"
                # If tool output is long, truncate in context (FR-05)
                raw = e.text_content
                if len(raw) > 1000:
                    content = f"[Tool Output truncated]: {raw[:600]}... [id: {e.id}]"
                else:
                    content = f"[Tool Output]: {raw}"
                tool_toks += estimate_tokens(content, provider_name)

            tok = estimate_tokens(content, provider_name)
            if recent_toks + tok > remaining_budget:
                break
            recent_toks += tok
            recent_messages.append({"role": role, "content": content})

        layer_tokens.recent_turns = recent_toks
        layer_tokens.tool_results = tool_toks

        # Put messages in chronological order
        messages.extend(reversed(recent_messages))
        messages.append({"role": "user", "content": new_user_message})

        return AssembledContext(
            system_prompt=full_system_text,
            messages=messages,
            layers=layer_tokens,
            total_tokens=layer_tokens.total,
            budget=budget,
            model_window=model_window,
        )
