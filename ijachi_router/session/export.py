"""Session exporter for audit and sharing.

Document 3.11 SC-13:
Session state shall be exportable as Markdown or JSON for audit and sharing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ijachi_router.session.events import CanonicalEvent
from ijachi_router.session.store import SessionStore


def export_session_json(store: SessionStore) -> str:
    """Export complete session data and event history as JSON."""
    events = [e.to_dict() for e in store.read_events(committed_only=True)]
    data = {
        "state": store.state.to_dict(),
        "events": events,
    }
    return json.dumps(data, indent=2)


def export_session_markdown(store: SessionStore) -> str:
    """Export session as a human-readable Markdown transcript."""
    st = store.state
    events = store.read_events(committed_only=True)

    lines = [
        f"# ijachi-llm-router Session Transcript: `{st.session_id}`",
        f"- **Workspace:** `{st.workspace_dir}`",
        f"- **Total Turns:** {st.turn_count}",
        f"- **Total Spend:** ${st.total_cost_usd:.4f}",
        f"- **Input/Output Tokens:** {st.total_input_tokens} in / {st.total_output_tokens} out",
        "",
        "## Facts & Decisions Ledger",
    ]
    if st.ledger.entries:
        for e in st.ledger.entries:
            lines.append(f"- **[{e.category}]** {e.fact}")
    else:
        lines.append("*No pinned facts recorded.*")

    lines.append("\n## Event Log\n")
    for evt in events:
        lines.append(f"### Turn {evt.turn}: `{evt.type}` ({evt.ts})")
        if evt.model:
            lines.append(f"*Model: {evt.model.get('provider')}/{evt.model.get('id')}*")

        if evt.type == "user_message":
            lines.append(f"\n> **User:** {evt.text_content}\n")
        elif evt.type == "assistant_message":
            lines.append(f"\n**Assistant:**\n\n{evt.text_content}\n")
        elif evt.type == "tool_call":
            tc = evt.tool_call
            lines.append(f"\n```json\n// Tool Call: {tc.get('name')}\n{json.dumps(tc.get('args', {}), indent=2)}\n```\n")
        elif evt.type == "tool_result":
            content_str = evt.text_content
            lines.append(f"\n```text\n// Tool Result:\n{content_str[:1000]}\n```\n")

    return "\n".join(lines)
